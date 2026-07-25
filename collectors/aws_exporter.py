"""
AWS CloudWatch / Cost Explorer 기반 자원·비용 수집 모듈
- CPU: Namespace AWS/EC2
- Memory/Disk: Namespace CWAgent (CloudWatch Agent 설치 필요, 2주차 Day1에서 설치함)
- 비용: Cost Explorer(us-east-1 고정) 서비스별 일별 조회 (decisions/0002 기준)
- 자원 사용률은 구간 "전체 평균"으로 계산 (GCP 기준, decisions/0001)
"""
import boto3
from datetime import datetime, timedelta, timezone

REGION = "ap-northeast-2"
cw = boto3.client("cloudwatch", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)

INSTANCE_SPECS = {
    "t3.micro": {"vcpu": 2, "ram_gb": 1},
    "t3.small": {"vcpu": 2, "ram_gb": 2},
    "t3.medium": {"vcpu": 2, "ram_gb": 4},
}


def _get_metric_average(namespace, metric_name, dimensions):
    """CloudWatch에서 최근 1시간 '구간 전체 평균'을 가져온다. 데이터 없으면 None.

    GCP(팀장) 기준과 맞추기 위해, 마지막 5분 값 1개가 아니라
    구간 내 모든 datapoint의 평균을 낸다 (decisions/0001).
    """
    response = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
        EndTime=datetime.now(timezone.utc),
        Period=300,
        Statistics=["Average"],
    )
    datapoints = response["Datapoints"]
    if not datapoints:
        return None
    avg = sum(d["Average"] for d in datapoints) / len(datapoints)
    return round(avg, 2)


def collect_resource_metrics(instance_id):
    """CPU, 메모리, 디스크 사용률을 한 번에 수집한다."""
    cpu = _get_metric_average(
        "AWS/EC2", "CPUUtilization",
        [{"Name": "InstanceId", "Value": instance_id}],
    )
    memory = _get_metric_average(
        "CWAgent", "mem_used_percent",
        [{"Name": "InstanceId", "Value": instance_id}],
    )
    disk = _get_metric_average(
        "CWAgent", "disk_used_percent",
        [
            {"Name": "InstanceId", "Value": instance_id},
            {"Name": "path", "Value": "/"},
            {"Name": "device", "Value": "nvme0n1p1"},
            {"Name": "fstype", "Value": "xfs"},
        ],
    )
    return cpu, memory, disk


def get_instance_type(instance_id):
    """인스턴스 타입을 조회한다."""
    response = ec2.describe_instances(InstanceIds=[instance_id])
    instance = response["Reservations"][0]["Instances"][0]
    return instance["InstanceType"]


def to_common_record(instance_id, cpu, memory, disk, instance_type):
    """자원 메트릭을 팀 공통 스키마(GCP 기준)로 변환한다."""
    return {
        "cloud": "AWS",
        "instance_id": instance_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cpu_avg": round(cpu, 2) if cpu is not None else None,
        "memory_avg": round(memory, 2) if memory is not None else None,
        "disk_avg": round(disk, 2) if disk is not None else None,
        "instance_type": instance_type,
        "vcpu": INSTANCE_SPECS.get(instance_type, {}).get("vcpu"),
        "ram_gb": INSTANCE_SPECS.get(instance_type, {}).get("ram_gb"),
        "cost_monthly": None,  # 자원 레코드엔 비용 직접 연결 안 함(별도 cost_records 사용)
    }


def collect_and_normalize(instance_id):
    """수집 + 사양 조회 + 공통 형식 변환을 한 번에 처리한다."""
    cpu, memory, disk = collect_resource_metrics(instance_id)
    instance_type = get_instance_type(instance_id)
    return to_common_record(instance_id, cpu, memory, disk, instance_type)


# ---------------------------------------------------------------------------
# 비용 수집 (3주차, decisions/0002 기준: 서비스별 여러 행 + 전 서비스 포함)
# ---------------------------------------------------------------------------

def to_common_cost_record(date, amount, unit, service):
    """AWS 비용 원본 → 팀 공통 비용 레코드로 변환한다 (GCP/Azure와 동일 형식)."""
    return {
        "cloud": "AWS",
        "date": date,
        "cost_usd": float(amount),
        "currency": unit,        # Cost Explorer UnblendedCost 단위는 이미 USD → 변환 불필요
        "service": service,
        "granularity": "DAILY",
    }


def collect_cost(start_date=None, end_date=None):
    """계정의 서비스별 일별 비용을 공통 레코드 리스트로 반환한다.

    - Cost Explorer는 리전에 안 묶인 글로벌 서비스 → region_name="us-east-1" 고정
    - decisions/0002: 특정 서비스로 필터하지 않고 전 서비스를 SERVICE 기준으로 그룹핑
    - 기본 조회 범위: 최근 7일
    """
    ce = boto3.client("ce", region_name="us-east-1")

    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    records = []
    try:
        response = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except Exception as e:  # 권한/데이터 문제로 끊기지 않게 방어 (GCP fallback 패턴 참고)
        print(f"Cost Explorer 조회 실패: {e}")
        return records

    for result in response["ResultsByTime"]:
        date = result["TimePeriod"]["Start"]
        for group in result["Groups"]:
            service = group["Keys"][0]
            metric = group["Metrics"]["UnblendedCost"]
            records.append(
                to_common_cost_record(date, metric["Amount"], metric["Unit"], service)
            )
    return records


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="AWS 자원/비용 수집기")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="서버 전송 없이 수집 결과를 공통 JSON으로 출력한다.",
    )
    parser.add_argument(
        "--instance-id",
        default="i-05f7cdc5c5183e2ae",
        help="자원 메트릭을 조회할 EC2 인스턴스 ID",
    )
    args = parser.parse_args()

    if not args.dry_run:
        print("현재는 --dry-run 모드만 지원합니다.")
        print("실행 예: python collectors/aws_exporter.py --dry-run")
    else:
        record = collect_and_normalize(args.instance_id)
        cost_records = collect_cost()

        print("=== RESOURCE METRIC ===")
        print(json.dumps(record, indent=2, ensure_ascii=False))

        print("\n=== COST RECORDS ===")
        print(json.dumps(cost_records, indent=2, ensure_ascii=False))

        if not cost_records:
            print("\n[주의] 비용 레코드가 비어 있습니다. 프리티어라 $0이거나 데이터 지연일 수 있습니다.")
