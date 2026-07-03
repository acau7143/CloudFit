import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from azure.identity import ClientSecretCredential
from azure.mgmt.monitor import MonitorManagementClient

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")
subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
resource_group = os.getenv("AZURE_RESOURCE_GROUP")
vm_name = os.getenv("AZURE_VM_NAME")

required = {
    "AZURE_TENANT_ID": tenant_id,
    "AZURE_CLIENT_ID": client_id,
    "AZURE_CLIENT_SECRET": client_secret,
    "AZURE_SUBSCRIPTION_ID": subscription_id,
    "AZURE_RESOURCE_GROUP": resource_group,
    "AZURE_VM_NAME": vm_name,
}

missing = [key for key, value in required.items() if not value]

if missing:
    print("누락된 환경변수:", ", ".join(missing))
    raise SystemExit(1)

credential = ClientSecretCredential(
    tenant_id=tenant_id,
    client_id=client_id,
    client_secret=client_secret,
)

client = MonitorManagementClient(credential, subscription_id)

resource_uri = (
    f"/subscriptions/{subscription_id}"
    f"/resourceGroups/{resource_group}"
    f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
)

end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(minutes=30)

start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

timespan = f"{start_str}/{end_str}"

print("timespan:", timespan)

metrics = client.metrics.list(
    resource_uri,
    timespan=timespan,
    interval="PT5M",
    metricnames="Percentage CPU",
    aggregation="Average",
)

found = False

for metric in metrics.value:
    print(f"metric name: {metric.name.value}")

    for timeseries in metric.timeseries:
        for data in timeseries.data:
            if data.average is not None:
                print("timestamp:", data.time_stamp)
                print("average_cpu_percent:", data.average)
                found = True

if not found:
    print("CPU 데이터가 아직 없습니다. VM 실행 후 몇 분 더 기다린 뒤 다시 실행하세요.")