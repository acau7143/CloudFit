import os
from dotenv import load_dotenv
from azure.identity import ClientSecretCredential

load_dotenv()

tenant_id = os.getenv("AZURE_TENANT_ID")
client_id = os.getenv("AZURE_CLIENT_ID")
client_secret = os.getenv("AZURE_CLIENT_SECRET")
subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")

required = {
    "AZURE_TENANT_ID": tenant_id,
    "AZURE_CLIENT_ID": client_id,
    "AZURE_CLIENT_SECRET": client_secret,
    "AZURE_SUBSCRIPTION_ID": subscription_id,
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

token = credential.get_token("https://management.azure.com/.default")

print("Azure Service Principal 인증 성공")
print("subscription_id_loaded:", bool(subscription_id))
print("token_expires_on:", token.expires_on)