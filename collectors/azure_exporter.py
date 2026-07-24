"""
Azure VM resource metric collector.
GCP/AWS와 동일한 공통 스키마(instance_id, cpu_avg, memory_avg, disk_avg)로 맞춘 버전.
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
import requests

DEFAULT_INTERVAL = "PT5M"
DEFAULT_LOOKBACK_MINUTES = 30
DEFAULT_COST_LOOKBACK_DAYS = 7
DEFAULT_REGION = "koreacentral"

EXCHANGE_RATE = {
    "KRW": 1350.0,
    "USD": 1.0,
}


SERVER_URL = "http://localhost:8000"  # 나중에 .env로 빼기


def send_resource_to_server(record: Dict[str, Any]) -> bool:
    """수집한 자원 메트릭을 중앙 서버 API로 전송"""
    try:
        response = requests.post(f"{SERVER_URL}/resources", json=record, timeout=5)
        if response.status_code == 201:
            print(f"[OK] 자원 데이터 저장 성공: {record['instance_id']}")
            return True
        else:
            print(f"[FAIL] 서버 응답 오류: {response.status_code} {response.text}", file=sys.stderr)
            return False
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] 서버 연결 실패: {SERVER_URL} 접속 불가", file=sys.stderr)
        return False
    except Exception as error:
        print(f"[FAIL] 예외 발생: {error}", file=sys.stderr)
        return False


def send_cost_to_server(record: Dict[str, Any]) -> bool:
    """수집한 비용 데이터를 중앙 서버 API로 전송"""
    try:
        response = requests.post(f"{SERVER_URL}/costs", json=record, timeout=5)
        return response.status_code == 201
    except Exception as error:
        print(f"[FAIL] 비용 데이터 전송 실패: {error}", file=sys.stderr)
        return False


def load_config() -> Dict[str, str]:
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
            "누락된 환경변수: " + ", ".join(missing) + "\n.env 파일을 확인하세요."
        )
    return config


def build_credential(config: Dict[str, str]) -> ClientSecretCredential:
    return ClientSecretCredential(
        tenant_id=config["tenant_id"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
    )


def build_resource_uri(config: Dict[str, str]) -> str:
    return (
        f"/subscriptions/{config['subscription_id']}"
        f"/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.Compute/virtualMachines/{config['vm_name']}"
    )


def make_timespan(lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES) -> str:
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)
    return f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def query_cpu_metric(
    client: MonitorManagementClient,
    resource_uri: str,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    interval: str = DEFAULT_INTERVAL,
    max_retries: int = 2,
) -> Optional[float]:
    # GCP와 동일하게 "최근 값 1개"가 아니라 구간 내 전체 평균으로 계산
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
            values = []
            for metric in metrics.value:
                for timeseries in metric.timeseries:
                    for data in timeseries.data:
                        if data.average is not None:
                            values.append(float(data.average))
            if not values:
                return None
            return round(sum(values) / len(values), 2)
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
) -> Dict[str, Optional[float]]:
    query = f"""
Perf
| where Computer =~ "{vm_name}"
| where CounterName in ("% Used Memory", "% Used Space")
| where CounterName == "% Used Memory"
    or (CounterName == "% Used Space" and InstanceName == "/")
| project TimeGenerated, CounterName, InstanceName, CounterValue
"""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            result = client.query_workspace(
                workspace_id=workspace_id, query=query, timespan=timedelta(hours=1)
            )
            if result.status == LogsQueryStatus.PARTIAL:
                tables = result.partial_data
                if result.partial_error is not None:
                    print(f"[WARN] Log Analytics 일부 결과만 반환됨: {result.partial_error}", file=sys.stderr)
            else:
                tables = result.tables

            if not tables:
                return {"memory_avg": None, "disk_avg": None}

            table = tables[0]
            columns = list(table.columns)
            rows = [dict(zip(columns, row)) for row in table.rows]

            memory_values, disk_values = [], []
            for row in rows:
                counter_name = row.get("CounterName")
                instance_name = row.get("InstanceName")
                counter_value = row.get("CounterValue")
                if counter_name == "% Used Memory" and counter_value is not None:
                    memory_values.append(float(counter_value))
                if counter_name == "% Used Space" and instance_name == "/" and counter_value is not None:
                    disk_values.append(float(counter_value))

            memory_avg = round(sum(memory_values) / len(memory_values), 2) if memory_values else None
            disk_avg = round(sum(disk_values) / len(disk_values), 2) if disk_values else None
            return {"memory_avg": memory_avg, "disk_avg": disk_avg}

        except (HttpResponseError, ServiceRequestError) as error:
            last_error = error
            if attempt < max_retries:
                time.sleep(2)
                continue
            raise RuntimeError(f"Log Analytics 메모리/디스크 조회 실패: {error}") from error
    raise RuntimeError(f"Log Analytics 메모리/디스크 조회 실패: {last_error}")


def query_vm_spec(
    client: ComputeManagementClient, resource_group: str, vm_name: str, region: str
) -> Dict[str, Optional[Any]]:
    vm = client.virtual_machines.get(resource_group_name=resource_group, vm_name=vm_name)
    if vm.hardware_profile is None or vm.hardware_profile.vm_size is None:
        raise RuntimeError("VM Size 정보를 확인할 수 없습니다.")

    vm_size = str(vm.hardware_profile.vm_size)
    vcpu: Optional[int] = None
    ram_gb: Optional[float] = None

    for sku in client.resource_skus.list(filter=f"location eq '{region}'"):
        if sku.resource_type != "virtualMachines" or sku.name != vm_size:
            continue
        capabilities = {c.name: c.value for c in (sku.capabilities or [])}
        if capabilities.get("vCPUs") is not None:
            vcpu = int(float(capabilities["vCPUs"]))
        if capabilities.get("MemoryGB") is not None:
            ram_gb = float(capabilities["MemoryGB"])
        break

    return {"instance_type": vm_size, "vcpu": vcpu, "ram_gb": ram_gb}


def to_usd(amount: float, currency: str) -> float:
    if currency not in EXCHANGE_RATE:
        raise ValueError(f"지원하지 않는 통화: {currency}")
    return round(float(amount) / EXCHANGE_RATE[currency], 6)


def to_common_cost_record(row: Dict[str, Any]) -> Dict[str, Any]:
    raw_cost = float(row["Cost"])
    usage_date = str(row["UsageDate"])
    currency = str(row["Currency"])
    date_str = f"{usage_date[:4]}-{usage_date[4:6]}-{usage_date[6:8]}"
    return {
        "cloud": "Azure",
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
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    query = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=start_time, to=end_time),
        dataset=QueryDataset(
            granularity="Daily",
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            grouping=[
                QueryGrouping(type="Dimension", name="ServiceName"),
                QueryGrouping(type="Dimension", name="ResourceId"),
            ],
        ),
    )
    scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
    result = client.query.usage(scope=scope, parameters=query)

    columns = [c.name for c in (result.columns or [])]
    return [dict(zip(columns, row)) for row in (result.rows or [])]


def collect_resource_metrics(resource_uri: Optional[str] = None) -> Dict[str, Any]:
    config = load_config()
    credential = build_credential(config)

    monitor_client = MonitorManagementClient(credential=credential, subscription_id=config["subscription_id"])
    compute_client = ComputeManagementClient(credential=credential, subscription_id=config["subscription_id"])
    logs_client = LogsQueryClient(credential)

    target_resource_uri = resource_uri or build_resource_uri(config)

    cpu_avg = query_cpu_metric(monitor_client, target_resource_uri)
    guest_result = query_guest_metrics(logs_client, config["workspace_id"], config["vm_name"])
    vm_spec = query_vm_spec(compute_client, config["resource_group"], config["vm_name"], config["region"])

    return {
        "cloud": "Azure",
        "instance_id": config["vm_name"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_avg": cpu_avg,
        "memory_avg": guest_result["memory_avg"],
        "disk_avg": guest_result["disk_avg"],
        "instance_type": vm_spec["instance_type"],
        "vcpu": vm_spec["vcpu"],
        "ram_gb": vm_spec["ram_gb"],
        "cost_monthly": None,
    }


def to_common_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cloud": raw["cloud"],
        "instance_id": raw["instance_id"],
        "timestamp": raw["timestamp"],
        "cpu_avg": raw["cpu_avg"],
        "memory_avg": raw["memory_avg"],
        "disk_avg": raw["disk_avg"],
        "instance_type": raw["instance_type"],
        "vcpu": raw["vcpu"],
        "ram_gb": raw["ram_gb"],
        "cost_monthly": raw["cost_monthly"],
    }


def run_dry_run() -> None:
    raw = collect_resource_metrics()
    record = to_common_record(raw)

    config = load_config()
    credential = build_credential(config)
    cost_client = CostManagementClient(credential)
    cost_rows = collect_cost(cost_client, config["subscription_id"], config["resource_group"])
    cost_records = [to_common_cost_record(row) for row in cost_rows]

    print("=== RESOURCE METRICS ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print("\n=== COST RECORDS ===")
    print(json.dumps(cost_records, indent=2, ensure_ascii=False))

    if record["cpu_avg"] is None:
        print("\n[주의] CPU 값이 null입니다. VM이 꺼져 있거나 최근 구간 내 메트릭이 없을 수 있습니다.", file=sys.stderr)
    if record["memory_avg"] is None:
        print("\n[주의] 메모리 값이 null입니다. AMA, DCR, LAW 데이터 유입 상태를 확인하세요.", file=sys.stderr)
    if record["disk_avg"] is None:
        print("\n[주의] 디스크 값이 null입니다. 루트 파일시스템(/)의 Perf 데이터가 있는지 확인하세요.", file=sys.stderr)


def run_send() -> None:
    """수집한 자원 메트릭과 비용 데이터를 dry-run 없이 실제 서버로 전송"""
    raw = collect_resource_metrics()
    record = to_common_record(raw)

    print("=== 자원 데이터 전송 시도 ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    send_resource_to_server(record)

    config = load_config()
    credential = build_credential(config)
    cost_client = CostManagementClient(credential)
    cost_rows = collect_cost(cost_client, config["subscription_id"], config["resource_group"])
    cost_records = [to_common_cost_record(row) for row in cost_rows]

    print("\n=== 비용 데이터 전송 시도 ===")
    for cost_record in cost_records:
        print(json.dumps(cost_record, indent=2, ensure_ascii=False))
        send_cost_to_server(cost_record)


def main() -> None:
    parser = argparse.ArgumentParser(description="Azure VM resource metric collector")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.dry_run:
            run_dry_run()
        else:
            run_send()
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
