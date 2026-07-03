"""
AWS CloudWatch 기반 자원 수집 모듈
- CPU: Namespace AWS/EC2
- Memory/Disk: Namespace CWAgent (CloudWatch Agent 설치 필요, 2주차 Day1에서 설치함)
- 참고: disk_used_percent는 이 계정에서 통계 API 반영이 지연되고 있어 임시로 None 처리
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
    """CloudWatch에서 최근 1시간 평균값 1개를 가져온다. 데이터 없으면 None."""
    response = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
        EndTime=datetime.now(timezone.utc),
        Period=300,
        Statistics=["Average"],
    )
    datapoints = sorted(response["Datapoints"], key=lambda d: d["Timestamp"])
    if not datapoints:
        return None
    return round(datapoints[-1]["Average"], 2)


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
    """팀 공통 스키마(팀장 계획표 기준)로 변환한다."""
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
        "cost_monthly": None,  # 3주차에 채울 예정
    }


def collect_and_normalize(instance_id):
    """수집 + 사양 조회 + 공통 형식 변환을 한 번에 처리한다."""
    cpu, memory, disk = collect_resource_metrics(instance_id)
    instance_type = get_instance_type(instance_id)
    return to_common_record(instance_id, cpu, memory, disk, instance_type)


if __name__ == "__main__":
    import json
    instance_id = "i-05f7cdc5c5183e2ae"
    print(json.dumps(collect_and_normalize(instance_id), indent=2, ensure_ascii=False))