"""
Azure VM resource metric collector.

Day 04 목표:
- .env에서 Azure 인증 정보 읽기
- Service Principal로 Azure Monitor API 인증
- VM의 Percentage CPU 메트릭 수집
- AWS/GCP와 맞출 수 있는 공통 형식으로 변환
- --dry-run 옵션으로 서버 전송 없이 JSON 출력 검증
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient

from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryGrouping,
    QueryTimePeriod,
)

from azure.mgmt.monitor import MonitorManagementClient
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from dotenv import load_dotenv


DEFAULT_INTERVAL = "PT5M"
DEFAULT_LOOKBACK_MINUTES = 30
DEFAULT_COST_LOOKBACK_DAYS = 7
DEFAULT_REGION = "koreacentral"


EXCHANGE_RATE = {
    "KRW": 1350.0,
    "USD": 1.0,
}


def load_config() -> Dict[str, str]:
    """
    .env 파일에서 Azure 수집에 필요한 설정을 읽는다.

    필요한 값:
    - AZURE_TENANT_ID
    - AZURE_CLIENT_ID
    - AZURE_CLIENT_SECRET
    - AZURE_SUBSCRIPTION_ID
    - AZURE_RESOURCE_GROUP
    - AZURE_VM_NAME
    """

    load_dotenv()

    config = {
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "client_id": os.getenv("AZURE_CLIENT_ID"),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET"),
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID"),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP"),
        "vm_name": os.getenv("AZURE_VM_NAME"),
        "workspace_id": os.getenv("AZURE_LOG_WORKSPACE_ID"),
        "region": os.getenv("AZURE_REGION", DEFAULT_REGION),
    }

    missing = [key for key, value in config.items() if not value]

    if missing:
        raise RuntimeError(
            "누락된 환경변수: "
            + ", ".join(missing)
            + "\n.env 파일에 Azure 인증 정보가 들어 있는지 확인하세요."
        )

    return config


def build_credential(config: Dict[str, str]) -> ClientSecretCredential:
    """
    Service Principal 인증 객체를 만든다.

    참고:
    Azure SDK의 ClientSecretCredential은 토큰이 만료되면 내부적으로 다시 토큰을 발급받는다.
    그래서 일반적인 토큰 만료는 SDK가 처리한다.
    """

    return ClientSecretCredential(
        tenant_id=config["tenant_id"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
    )


def build_resource_uri(config: Dict[str, str]) -> str:
    """
    Azure Monitor API가 VM을 찾을 수 있도록 resource URI를 만든다.
    """

    return (
        f"/subscriptions/{config['subscription_id']}"
        f"/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.Compute/virtualMachines/{config['vm_name']}"
    )


def make_timespan(lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES) -> str:
    """
    Azure Monitor API가 요구하는 ISO 8601 시간 범위를 만든다.

    예:
    2026-07-02T10:30:18Z/2026-07-02T11:00:18Z
    """

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    return f"{start_str}/{end_str}"


def format_timestamp(value: datetime) -> str:
    """
    Azure SDK가 반환한 datetime을 공통 UTC 문자열로 바꾼다.
    """

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_cpu_metric(
    client: MonitorManagementClient,
    resource_uri: str,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    interval: str = DEFAULT_INTERVAL,
    max_retries: int = 2,
) -> Dict[str, Optional[Any]]:
    """
    Azure Monitor에서 Percentage CPU를 조회한다.

    실패 가능성:
    - VM이 너무 최근에 켜져서 메트릭이 아직 없음
    - timespan 형식 오류
    - 권한 부족
    - 네트워크/API 일시 오류
    """

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            metrics = client.metrics.list(
                resource_uri,
                timespan=make_timespan(lookback_minutes),
                interval=interval,
                metricnames="Percentage CPU",
                aggregation="Average",
            )

            latest_timestamp: Optional[str] = None
            latest_cpu: Optional[float] = None

            for metric in metrics.value:
                for timeseries in metric.timeseries:
                    for data in timeseries.data:
                        if data.average is not None and data.time_stamp is not None:
                            latest_timestamp = format_timestamp(data.time_stamp)
                            latest_cpu = float(data.average)

            return {
                "timestamp": latest_timestamp,
                "cpu_percent": latest_cpu,
            }

        except (HttpResponseError, ServiceRequestError) as error:
            last_error = error

            if attempt < max_retries:
                time.sleep(2)
                continue

            raise RuntimeError(f"Azure Monitor CPU 조회 실패: {error}") from error

    raise RuntimeError(f"Azure Monitor CPU 조회 실패: {last_error}")


def query_guest_metrics(
    client: LogsQueryClient,
    workspace_id: str,
    vm_name: str,
    max_retries: int = 2,
) -> Dict[str, Optional[Any]]:
    """
    Log Analytics Workspace의 Perf 테이블에서
    VM의 메모리 사용률과 루트 디스크 사용률을 조회한다.

    조회 대상:
    - Memory / % Used Memory
    - Logical Disk / % Used Space / InstanceName="/"
    """

    query = f"""
Perf
| where Computer =~ "{vm_name}"
| where CounterName in ("% Used Memory", "% Used Space")
| where CounterName == "% Used Memory"
    or (CounterName == "% Used Space" and InstanceName == "/")
| order by TimeGenerated desc
| project TimeGenerated, CounterName, InstanceName, CounterValue
"""

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            result = client.query_workspace(
                workspace_id=workspace_id,
                query=query,
                timespan=timedelta(hours=1),
            )

            if result.status == LogsQueryStatus.PARTIAL:
                tables = result.partial_data

                if result.partial_error is not None:
                    print(
                        f"[WARN] Log Analytics 일부 결과만 반환됨: {result.partial_error}",
                        file=sys.stderr,
                    )
            else:
                tables = result.tables

            if not tables:
                return {
                    "memory_percent": None,
                    "disk_percent": None,
                }

            table = tables[0]

            # azure-monitor-query 2.0.0에서는 columns가 문자열 목록이다.
            columns = list(table.columns)

            rows = [
                dict(zip(columns, row))
                for row in table.rows
            ]

            memory_percent: Optional[float] = None
            disk_percent: Optional[float] = None

            for row in rows:
                counter_name = row.get("CounterName")
                instance_name = row.get("InstanceName")
                counter_value = row.get("CounterValue")

                if (
                    counter_name == "% Used Memory"
                    and memory_percent is None
                    and counter_value is not None
                ):
                    memory_percent = round(float(counter_value), 2)

                if (
                    counter_name == "% Used Space"
                    and instance_name == "/"
                    and disk_percent is None
                    and counter_value is not None
                ):
                    disk_percent = round(float(counter_value), 2)

                if memory_percent is not None and disk_percent is not None:
                    break

            return {
                "memory_percent": memory_percent,
                "disk_percent": disk_percent,
            }

        except (HttpResponseError, ServiceRequestError) as error:
            last_error = error

            if attempt < max_retries:
                time.sleep(2)
                continue

            raise RuntimeError(
                f"Log Analytics 메모리/디스크 조회 실패: {error}"
            ) from error

    raise RuntimeError(
        f"Log Analytics 메모리/디스크 조회 실패: {last_error}"
    )


def query_vm_spec(
    client: ComputeManagementClient,
    resource_group: str,
    vm_name: str,
    region: str,
) -> Dict[str, Optional[Any]]:
    """
    Azure Compute API에서 VM의 크기와 하드웨어 사양을 조회한다.

    반환:
    - instance_type: VM Size 이름
    - vcpu: vCPU 개수
    - ram_gb: 메모리 용량(GB)
    """

    vm = client.virtual_machines.get(
        resource_group_name=resource_group,
        vm_name=vm_name,
    )

    if vm.hardware_profile is None or vm.hardware_profile.vm_size is None:
        raise RuntimeError("VM Size 정보를 확인할 수 없습니다.")

    vm_size = str(vm.hardware_profile.vm_size)

    vcpu: Optional[int] = None
    ram_gb: Optional[float] = None

    skus = client.resource_skus.list(
        filter=f"location eq '{region}'"
    )

    for sku in skus:
        if sku.resource_type != "virtualMachines":
            continue

        if sku.name != vm_size:
            continue

        capabilities = {
            capability.name: capability.value
            for capability in (sku.capabilities or [])
        }

        vcpu_value = capabilities.get("vCPUs")
        memory_value = capabilities.get("MemoryGB")

        if vcpu_value is not None:
            vcpu = int(float(vcpu_value))

        if memory_value is not None:
            ram_gb = float(memory_value)

        break

    return {
        "instance_type": vm_size,
        "vcpu": vcpu,
        "ram_gb": ram_gb,
    }


def to_usd(amount: float, currency: str) -> float:
    """
    원본 비용을 USD 단위로 변환한다.
    """

    if currency not in EXCHANGE_RATE:
        raise ValueError(f"지원하지 않는 통화: {currency}")

    rate = EXCHANGE_RATE[currency]

    return round(float(amount) / rate, 6)


def to_common_cost_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Azure 비용 데이터를 공통 비용 레코드로 변환한다.
    """

    raw_cost = float(row["Cost"])
    usage_date = str(row["UsageDate"])
    currency = str(row["Currency"])

    date_str = (
        f"{usage_date[:4]}-"
        f"{usage_date[4:6]}-"
        f"{usage_date[6:8]}"
    )

    return {
        "cloud": "azure",
        "date": date_str,
        "cost_usd": to_usd(raw_cost, currency),
        "currency": "USD",
        "service": row["ServiceName"],
        "granularity": "DAILY",
    }


def collect_cost(
    client: CostManagementClient,
    subscription_id: str,
    resource_group: str,
    lookback_days: int = DEFAULT_COST_LOOKBACK_DAYS,
) -> list[Dict[str, Any]]:
    """
    Resource Group 범위의 Azure 비용을 일별로 조회한다.

    그룹 기준:
    - ServiceName
    - ResourceId
    """

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    query = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(
            from_property=start_time,
            to=end_time,
        ),
        dataset=QueryDataset(
            granularity="Daily",
            aggregation={
                "totalCost": QueryAggregation(
                    name="Cost",
                    function="Sum",
                )
            },
            grouping=[
                QueryGrouping(
                    type="Dimension",
                    name="ServiceName",
                ),
                QueryGrouping(
                    type="Dimension",
                    name="ResourceId",
                ),
            ],
        ),
    )

    scope = (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
    )

    result = client.query.usage(
        scope=scope,
        parameters=query,
    )

    columns = [
        column.name
        for column in (result.columns or [])
    ]

    rows = [
        dict(zip(columns, row))
        for row in (result.rows or [])
    ]

    return rows


def collect_resource_metrics(resource_uri: Optional[str] = None) -> Dict[str, Any]:
    """
    Azure VM의 자원 메트릭과 인스턴스 사양을 수집한다.

    수집 대상:
    - CPU: Azure Monitor Percentage CPU
    - Memory: Log Analytics Workspace Perf 테이블
    - Disk: Log Analytics Workspace Perf 테이블
    - VM Spec: Azure Compute API
    """

    config = load_config()
    credential = build_credential(config)

    monitor_client = MonitorManagementClient(
        credential=credential,
        subscription_id=config["subscription_id"],
    )

    compute_client = ComputeManagementClient(
        credential=credential,
        subscription_id=config["subscription_id"],
    )

    logs_client = LogsQueryClient(credential)

    target_resource_uri = resource_uri or build_resource_uri(config)

    cpu_result = query_cpu_metric(
        monitor_client,
        target_resource_uri,
    )

    guest_result = query_guest_metrics(
        logs_client,
        config["workspace_id"],
        config["vm_name"],
    )

    vm_spec = query_vm_spec(
        compute_client,
        config["resource_group"],
        config["vm_name"],
        config["region"],
    )

    return {
        "cloud": "azure",
        "resource_id": config["vm_name"],
        "resource_type": "vm",
        "region": config["region"],
        "metric_name": "Percentage CPU",
        "timestamp": cpu_result["timestamp"],
        "cpu_percent": cpu_result["cpu_percent"],
        "memory_percent": guest_result["memory_percent"],
        "disk_percent": guest_result["disk_percent"],
        "instance_type": vm_spec["instance_type"],
        "vcpu": vm_spec["vcpu"],
        "ram_gb": vm_spec["ram_gb"],
        "cost_monthly": None,
        "source": "actual",
    }


def to_common_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    AWS/GCP와 맞출 공통 레코드로 변환한다.

    지금은 팀 공통 스키마가 완전히 확정되기 전이므로,
    최소 공통 필드 중심으로 맞춘다.
    """

    return {
        "cloud": raw["cloud"],
        "resource_id": raw["resource_id"],
        "resource_type": raw["resource_type"],
        "region": raw["region"],
        "timestamp": raw["timestamp"],
        "cpu_percent": raw["cpu_percent"],
        "memory_percent": raw["memory_percent"],
        "disk_percent": raw["disk_percent"],
        "instance_type": raw["instance_type"],
        "vcpu": raw["vcpu"],
        "ram_gb": raw["ram_gb"],
        "cost_monthly": raw["cost_monthly"],
        "source": raw["source"],
    }


def run_dry_run() -> None:
    """
    서버 전송 없이 수집 결과를 화면에 출력한다.
    """

    raw = collect_resource_metrics()
    record = to_common_record(raw)

    config = load_config()
    credential = build_credential(config)

    cost_client = CostManagementClient(credential)

    cost_rows = collect_cost(
        cost_client,
        config["subscription_id"],
        config["resource_group"],
    )

    cost_records = [
        to_common_cost_record(row)
        for row in cost_rows
    ]

    print("=== RESOURCE METRICS ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))

    print("\n=== COST RECORDS ===")
    print(json.dumps(cost_records, indent=2, ensure_ascii=False))

    if record["cpu_percent"] is None:
        print(
            "\n[주의] CPU 값이 null입니다. VM이 꺼져 있거나, 최근 30분 내 Azure Monitor 메트릭이 없을 수 있습니다.",
            file=sys.stderr,
        )

    if record["memory_percent"] is None:
        print(
            "\n[주의] 메모리 값이 null입니다. AMA, DCR, LAW 데이터 유입 상태를 확인하세요.",
            file=sys.stderr,
        )

    if record["disk_percent"] is None:
        print(
            "\n[주의] 디스크 값이 null입니다. 루트 파일시스템(/)의 Perf 데이터가 있는지 확인하세요.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Azure VM resource metric collector")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Azure CPU 메트릭을 수집하고 공통 형식 JSON으로 출력합니다.",
    )

    args = parser.parse_args()

    if not args.dry_run:
        print("현재는 --dry-run 모드만 지원합니다.")
        print("실행 예: python collectors\\azure_exporter.py --dry-run")
        return

    try:
        run_dry_run()

    except ClientAuthenticationError as error:
        print("[ERROR] Azure 인증 실패", file=sys.stderr)
        print("확인할 것: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET", file=sys.stderr)
        print(error, file=sys.stderr)
        sys.exit(1)

    except RuntimeError as error:
        print("[ERROR] Azure 수집기 실행 실패", file=sys.stderr)
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()