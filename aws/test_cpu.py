import boto3
from datetime import datetime, timedelta, timezone

cloudwatch = boto3.client("cloudwatch", region_name="ap-northeast-2")

response = cloudwatch.get_metric_statistics(
    Namespace="AWS/EC2",
    MetricName="CPUUtilization",
    Dimensions=[{"Name": "InstanceId", "Value": "i-05f7cdc5c5183e2ae"}],
    StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
    EndTime=datetime.now(timezone.utc),
    Period=300,
    Statistics=["Average"],
)

datapoints = sorted(response["Datapoints"], key=lambda d: d["Timestamp"])

if not datapoints:
    print("호출 성공! 아직 데이터가 안 쌓였어요 (인스턴스가 방금 켜져서 그래요). 5~10분 뒤 다시 실행해보세요.")
else:
    print("호출 성공! CPU 사용률:")
    for d in datapoints:
        print(f"  {d['Timestamp']}  →  {round(d['Average'], 2)} %")