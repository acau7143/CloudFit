import os
import sys
import time
import requests
from dotenv import load_dotenv
from google.cloud import monitoring_v3
from google.api_core.exceptions import ResourceExhausted
from googleapiclient import discovery
from datetime import datetime, timedelta, timezone
from google.cloud import bigquery

try:
    from collectors import cloud_config
except ImportError:  # 스크립트로 직접 실행하면 collectors/가 sys.path[0]
    import cloud_config

# 프로젝트/존/인스턴스/청구 계정은 .env에서 읽는다 (cloud_config.py, .env.example 참고).

# Compute API 조회가 실패할 때(권한 없음 등)만 쓰는 폴백 표
MACHINE_SPECS = {
    'e2-micro':  {'vcpu': 2, 'ram_gb': 1},
    'e2-small':  {'vcpu': 2, 'ram_gb': 2},
    'e2-medium': {'vcpu': 2, 'ram_gb': 4},
}

GCP_PRICING = {
    'e2-micro':  0.0084,
    'e2-small':  0.0168,
    'e2-medium': 0.0336,
}


def _list_time_series_with_retry(client, request, max_retries=3):
    """Cloud Monitoring API 호출 + 할당량 초과(ResourceExhausted) 시 재시도.
    list_time_series는 호출 시점이 아니라 순회(iterate)할 때 실제 통신이 일어나므로,
    try 블록 안에서 list()로 끝까지 소비해야 재시도가 제대로 동작한다."""
    for attempt in range(max_retries + 1):
        try:
            return list(client.list_time_series(request=request))
        except ResourceExhausted as error:
            if attempt < max_retries:
                wait = 30 * (attempt + 1)  # 30초, 60초, 90초
                print(f"[WAIT] 할당량 초과 - {wait}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            print(f"[FAIL] 재시도 {max_retries}번 다 실패: {error}")
            raise


def collect_cpu(project_id):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)

    results = _list_time_series_with_retry(
        client,
        request={
            "name": project_name,
            "filter": 'metric.type="compute.googleapis.com/instance/cpu/utilization"',
            "interval": monitoring_v3.TimeInterval(
                end_time=now,
                start_time=now - timedelta(hours=1)
            ),
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    records = []
    for result in results:
        instance_id = result.resource.labels.get("instance_id", "unknown")
        for point in result.points:
            records.append({
                "timestamp": point.interval.end_time.isoformat(),
                "provider": "gcp",
                "instance_id": instance_id,
                "cpu_percent": round(point.value.double_value * 100, 2),
            })
    return records


def collect_memory(project_id):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)

    results = _list_time_series_with_retry(
        client,
        request={
            "name": project_name,
            "filter": 'metric.type="agent.googleapis.com/memory/percent_used" AND metric.label.state="used"',
            "interval": monitoring_v3.TimeInterval(
                end_time=now,
                start_time=now - timedelta(hours=1)
            ),
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    records = []
    for result in results:
        instance_id = result.resource.labels.get("instance_id", "unknown")
        for point in result.points:
            records.append({
                "timestamp": point.interval.end_time.isoformat(),
                "provider": "gcp",
                "instance_id": instance_id,
                "memory_percent": round(point.value.double_value, 2),
            })
    return records


def collect_disk(project_id, device=None):
    device = device or cloud_config.gcp_disk_device()
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)

    results = _list_time_series_with_retry(
        client,
        request={
            "name": project_name,
            "filter": (
                'metric.type="agent.googleapis.com/disk/percent_used" '
                f'AND metric.label.device="{device}" AND metric.label.state="used"'
            ),
            "interval": monitoring_v3.TimeInterval(
                end_time=now,
                start_time=now - timedelta(hours=1)
            ),
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }
    )

    records = []
    for result in results:
        instance_id = result.resource.labels.get("instance_id", "unknown")
        for point in result.points:
            records.append({
                "timestamp": point.interval.end_time.isoformat(),
                "provider": "gcp",
                "instance_id": instance_id,
                "disk_percent": round(point.value.double_value, 2),
            })
    return records


def get_instance_spec(project_id, zone, instance_name):
    compute = discovery.build('compute', 'v1')
    instance = compute.instances().get(
        project=project_id,
        zone=zone,
        instance=instance_name
    ).execute()
    machine_type_url = instance['machineType']
    return machine_type_url.split('/')[-1]


def get_machine_specs(project_id, zone, machine_type):
    """머신 타입의 vCPU/RAM(GB)을 Compute API로 조회한다. 실패하면 폴백 표, 거기도 없으면 {}."""
    try:
        compute = discovery.build('compute', 'v1')
        info = compute.machineTypes().get(
            project=project_id, zone=zone, machineType=machine_type
        ).execute()
        return {"vcpu": info["guestCpus"], "ram_gb": round(info["memoryMb"] / 1024, 2)}
    except Exception as e:  # 권한이 없어도 수집은 계속돼야 함
        print(f"[정보] 머신 타입 사양 API 조회 실패, 폴백 표 사용: {e}")
        return MACHINE_SPECS.get(machine_type, {})


def _average(records, key):
    if not records:
        return None
    values = [r[key] for r in records]
    return round(sum(values) / len(values), 2)


def to_common_record(instance_id, cpu_records, memory_records, disk_records, machine_type, specs=None):
    """specs: {"vcpu":.., "ram_gb":..}. 안 주면 폴백 표(MACHINE_SPECS)로 찾는다."""
    if specs is None:
        specs = MACHINE_SPECS.get(machine_type, {})
    return {
        "cloud": "GCP",
        "instance_id": instance_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_avg": _average(cpu_records, "cpu_percent"),
        "memory_avg": _average(memory_records, "memory_percent"),
        "disk_avg": _average(disk_records, "disk_percent"),
        "instance_type": machine_type,
        "vcpu": specs.get("vcpu"),
        "ram_gb": specs.get("ram_gb"),
        "cost_monthly": None,
    }


def estimate_daily_cost(machine_type: str, hours: int = 24) -> float:
    hourly = GCP_PRICING.get(machine_type, 0.0)
    return round(hourly * hours, 6)


def to_common_cost_record(date, cost_usd: float, service: str = 'Compute Engine') -> dict:
    return {
        "cloud": "GCP",
        "date": str(date),
        "cost_usd": float(cost_usd),
        "currency": "USD",
        "service": service,
        "granularity": "DAILY"
    }


def collect_cost(project_id: str, billing_account_id: str, machine_type: str = 'e2-micro') -> list[dict]:
    try:
        client = bigquery.Client(project=project_id)
        table_id = billing_account_id.replace("-", "_")
        query = f"""
            SELECT
                DATE(usage_start_time) AS date,
                service.description AS service,
                SUM(cost / currency_conversion_rate) AS total_cost_usd
            FROM `{project_id}.billing_export.gcp_billing_export_v1_{table_id}`
            WHERE DATE(usage_start_time) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND CURRENT_DATE()
            GROUP BY date, service
            ORDER BY date, service
        """
        rows = list(client.query(query).result())
        if rows:
            return [
                to_common_cost_record(r.date, r.total_cost_usd, r.service)
                for r in rows
            ]
    except Exception as e:
        print(f"BigQuery 조회 실패 또는 데이터 없음: {e}")

    today = datetime.utcnow().date().isoformat()
    return [to_common_cost_record(today, estimate_daily_cost(machine_type))]


load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")


def send_resource_to_server(record: dict) -> bool:
    try:
        response = requests.post(
            f"{SERVER_URL}/resources",
            json=record,
            timeout=5
        )
        if response.status_code == 201:
            print(f"[OK] 자원 데이터 저장 성공: {record['instance_id']}")
            return True
        else:
            print(f"[FAIL] 서버 응답 오류: {response.status_code} {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] 서버 연결 실패: {SERVER_URL} 접속 불가")
        return False
    except Exception as e:
        print(f"[FAIL] 예외 발생: {e}")
        return False


def send_cost_to_server(record: dict) -> bool:
    try:
        response = requests.post(
            f"{SERVER_URL}/costs",
            json=record,
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=5
        )
        if response.status_code == 201:
            print(f"[OK] 비용 데이터 저장 성공: {record['date']}")
            return True
        else:
            print(f"[FAIL] 서버 응답 오류: {response.status_code} {response.text}")
            return False
    except Exception as e:
        print(f"[FAIL] 비용 데이터 전송 실패: {e}")
        return False


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv

    # 설정이 빠졌으면 수집을 시작하기 전에 빠진 키를 한 번에 안내하고 종료
    settings = cloud_config.exit_on_config_error(
        cloud_config.require_env,
        "GCP_PROJECT_ID", "GCP_ZONE", "GCP_INSTANCE_NAME", "GCP_BILLING_ACCOUNT_ID",
    )
    PROJECT_ID = settings["GCP_PROJECT_ID"]
    ZONE = settings["GCP_ZONE"]
    INSTANCE_NAME = settings["GCP_INSTANCE_NAME"]
    BILLING_ACCOUNT_ID = settings["GCP_BILLING_ACCOUNT_ID"]

    cpu_records = collect_cpu(PROJECT_ID)
    memory_records = collect_memory(PROJECT_ID)
    disk_records = collect_disk(PROJECT_ID)
    machine_type = get_instance_spec(PROJECT_ID, ZONE, INSTANCE_NAME)
    specs = get_machine_specs(PROJECT_ID, ZONE, machine_type)

    instance_id = cpu_records[0]["instance_id"] if cpu_records else "unknown"
    record = to_common_record(instance_id, cpu_records, memory_records, disk_records, machine_type, specs)

    cost_records = collect_cost(PROJECT_ID, BILLING_ACCOUNT_ID, machine_type=machine_type)

    if dry_run:
        print(record)
        print("=== 비용 데이터 수집 테스트 ===")
        for r in cost_records:
            print(r)
    else:
        send_resource_to_server(record)
        for r in cost_records:
            send_cost_to_server(r)
