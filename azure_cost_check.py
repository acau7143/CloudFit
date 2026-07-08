import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from azure.identity import ClientSecretCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryGrouping,
    QueryTimePeriod,
)


load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"누락된 환경변수: {name}")

    return value


tenant_id = get_required_env("AZURE_TENANT_ID")
client_id = get_required_env("AZURE_CLIENT_ID")
client_secret = get_required_env("AZURE_CLIENT_SECRET")
subscription_id = get_required_env("AZURE_SUBSCRIPTION_ID")


credential = ClientSecretCredential(
    tenant_id=tenant_id,
    client_id=client_id,
    client_secret=client_secret,
)

client = CostManagementClient(credential)


end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(days=7)


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


resource_group = get_required_env("AZURE_RESOURCE_GROUP")

scope = (
    f"/subscriptions/{subscription_id}"
    f"/resourceGroups/{resource_group}"
)

result = client.query.usage(
    scope=scope,
    parameters=query,
)


print("=== COLUMNS ===")

for column in result.columns or []:
    print(column.name, column.type)


print("\n=== ROWS ===")

for row in result.rows or []:
    print(row)