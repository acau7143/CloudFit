import sys
from google.cloud import monitoring_v3
from googleapiclient import discovery
from datetime import datetime, timedelta, timezone

PROJECT_ID = "project-3f80ed2e-f0f6-4855-b15"
ZONE = "asia-northeast3-a"
INSTANCE_NAME = "finops-test"

MACHINE_SPECS = {
    'e2-micro':  {'vcpu': 2, 'ram_gb': 1},
    'e2-small':  {'vcpu': 2, 'ram_gb': 2},
    'e2-medium': {'vcpu': 2, 'ram_gb': 4},
}


def collect_cpu(project_id):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)
    results = client.list_time_series(
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
    results = client.list_time_series(
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


def collect_disk(project_id):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    now = datetime.now(timezone.utc)
    results = client.list_time_series(
        request={
            "name": project_name,
            "filter": 'metric.type="agent.googleapis.com/disk/percent_used" AND metric.label.device="/dev/sda1" AND metric.label.state="used"',
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


def _average(records, key):
    if not records:
        return None
    values = [r[key] for r in records]
    return round(sum(values) / len(values), 2)


def to_common_record(instance_id, cpu_records, memory_records, disk_records, machine_type):
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


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv

    cpu_records = collect_cpu(PROJECT_ID)
    memory_records = collect_memory(PROJECT_ID)
    disk_records = collect_disk(PROJECT_ID)
    machine_type = get_instance_spec(PROJECT_ID, ZONE, INSTANCE_NAME)

    instance_id = cpu_records[0]["instance_id"] if cpu_records else "unknown"

    record = to_common_record(instance_id, cpu_records, memory_records, disk_records, machine_type)
    print(record)
