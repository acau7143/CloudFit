import sys
from google.cloud import monitoring_v3
from datetime import datetime, timedelta, timezone

PROJECT_ID = "project-3f80ed2e-f0f6-4855-b15"

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

def to_common_record(raw):
    return raw

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    records = collect_cpu(PROJECT_ID)
    for r in records:
        print(r)
