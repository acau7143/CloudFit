"""
Azure 미사용 리소스(관리 디스크 / 공인 IP) 탐지기.

판정 기준:
- 디스크: disk_state == 'Unattached' (Reserved는 정지된 VM에 붙어있는 상태라 제외)
- 공인 IP: ip_configuration이 없음 (어떤 NIC/리소스에도 연결 안 됨)

범위:
- subscription 전체가 아니라 AZURE_RESOURCE_GROUP 하나로 한정.
  (aws_exporter가 REGION, gcp_exporter가 ZONE으로 좁히는 것과 같은 팀 컨벤션)

확정 방식 (decisions/0011 참고):
- 공인 IP는 생성 시각을 알 수 있는 필드가 없어서, 방금 만든 IP도 같은 조건에 걸릴 수 있음.
- 그래서 한 번 탐지됐다고 바로 "확정"하지 않고, 서버에 이미 활성 상태로 남아있는
  이전 탐지 기록과 대조해서 같은 resource_id가 다시 나오면 그때 "확정"으로 보고 알림을 보낸다.
- 처음 걸린 건 "후보"로 서버에 저장은 하되(다음 실행 때 비교할 수 있게), 알림은 안 보낸다.
- 디스크는 생성 시각 문제가 상대적으로 덜하지만, 팀 규칙 통일을 위해 동일한 확정 절차를 적용한다.

DB에는 직접 연결하지 않는다. Azure VM에서 "localhost"는 EC2 서버가 아니라
Azure 자기 자신을 가리키므로, 기존 수집기들과 동일하게 중앙 서버(FastAPI)에
HTTP로 저장을 위임한다 (server_client.py 재사용).
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from dotenv import load_dotenv
import requests

# collectors/와 server/는 형제 폴더라, collectors 안에서 스크립트를 실행하면
# Python이 기본적으로 server/ 폴더를 못 찾는다. 프로젝트 루트(이 파일의 부모의
# 부모 폴더)를 sys.path에 직접 추가해서, 팀원 누구나 별도 환경변수 설정 없이
# `from server.notifier import ...`가 바로 동작하게 한다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server_client as sc
from server.notifier import send_slack_alert

load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")


def load_config() -> Dict[str, str]:
    """이 스크립트에 필요한 최소한의 환경변수만 읽는다.

    azure_exporter.py의 load_config()는 vm_name/workspace_id도 필수로 요구해서
    그대로 재사용하면 이 스크립트에 필요 없는 값까지 없다고 에러가 난다.
    """
    config = {
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "client_id": os.getenv("AZURE_CLIENT_ID"),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET"),
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID"),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP"),
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


def find_unattached_disks(
    compute_client: ComputeManagementClient, resource_group: str
) -> List[Dict[str, Any]]:
    """리소스 그룹 범위에서 Unattached 상태인 관리 디스크를 찾는다."""
    candidates = []
    for disk in compute_client.disks.list_by_resource_group(resource_group):
        if disk.disk_state == "Unattached":
            candidates.append(
                {
                    "cloud": "Azure",
                    "resource_type": "disk",
                    "resource_id": disk.name,
                    "reason": "disk_state=Unattached (미연결 관리 디스크)",
                }
            )
    return candidates


def find_unassociated_public_ips(
    network_client: NetworkManagementClient, resource_group: str
) -> List[Dict[str, Any]]:
    """리소스 그룹 범위에서 어떤 NIC에도 안 붙은 공인 IP를 찾는다."""
    candidates = []
    for ip in network_client.public_ip_addresses.list(resource_group):
        if ip.ip_configuration is None:
            candidates.append(
                {
                    "cloud": "Azure",
                    "resource_type": "ip",
                    "resource_id": ip.name,
                    "reason": "ip_configuration 없음 (미연결 공인 IP)",
                }
            )
    return candidates


def fetch_previously_active_resource_ids(cloud: str) -> Set[str]:
    """서버에 이미 활성(미해결) 상태로 남아있는 미사용 리소스의 resource_id 집합을 가져온다.

    이번 실행에서 새로 찾은 후보와 대조해서 "재탐지"인지 판단하는 데 쓴다.
    """
    try:
        response = requests.get(
            f"{SERVER_URL}/unused-resources",
            params={"cloud": cloud, "only_active": "true"},
            timeout=5,
        )
        response.raise_for_status()
        rows = response.json()
        return {row["resource_id"] for row in rows}
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] 서버 연결 실패: {SERVER_URL} 접속 불가", file=sys.stderr)
        return set()
    except Exception as error:
        print(f"[FAIL] 이전 탐지 기록 조회 실패: {error}", file=sys.stderr)
        return set()


def annotate_confirmation(
    candidates: List[Dict[str, Any]], previously_active_ids: Set[str]
) -> List[Dict[str, Any]]:
    """이전 활성 목록과 대조해서 각 후보를 '최초 탐지' 또는 '재탐지 확정'으로 구분한다."""
    for candidate in candidates:
        if candidate["resource_id"] in previously_active_ids:
            candidate["confirmed"] = True
            candidate["reason"] = f"{candidate['reason']} - 재탐지 확정"
        else:
            candidate["confirmed"] = False
            candidate["reason"] = f"{candidate['reason']} - 최초 탐지(후보)"
    return candidates


async def detect_unused(dry_run: bool = False) -> List[Dict[str, Any]]:
    """미사용 리소스를 탐지하고, dry_run이 아니면 서버로 전송한다.

    AWS 트랙과 함수 시그니처 패턴(async def detect_unused(dry_run) -> list[dict])을 맞춘다.
    내부 Azure SDK 호출 자체는 동기 함수라 await할 대상은 없지만,
    다른 클라우드 수집기와 나란히 놓고 비교하기 쉽도록 통일한다.
    """
    config = load_config()
    credential = build_credential(config)

    compute_client = ComputeManagementClient(
        credential=credential, subscription_id=config["subscription_id"]
    )
    network_client = NetworkManagementClient(
        credential=credential, subscription_id=config["subscription_id"]
    )

    disk_candidates = find_unattached_disks(compute_client, config["resource_group"])
    ip_candidates = find_unassociated_public_ips(network_client, config["resource_group"])
    all_candidates = disk_candidates + ip_candidates

    previously_active_ids = fetch_previously_active_resource_ids("Azure")
    all_candidates = annotate_confirmation(all_candidates, previously_active_ids)

    if dry_run:
        return all_candidates

    for candidate in all_candidates:
        payload = {k: v for k, v in candidate.items() if k != "confirmed"}
        response = sc.post_unused_resource(payload)
        if response.status_code == 201:
            print(f"[OK] 저장 성공: {candidate['resource_type']} {candidate['resource_id']}")
        else:
            print(
                f"[FAIL] 서버 응답 오류: {response.status_code} {response.text}",
                file=sys.stderr,
            )

        # 알림은 '재탐지 확정'된 것만 보낸다 (최초 탐지=후보는 조용히 저장만).
        if candidate["confirmed"]:
            send_slack_alert(
                title="[미사용 리소스 재탐지 확정] Azure",
                message=f"{candidate['resource_type']} {candidate['resource_id']} - {candidate['reason']}",
            )
            print(f"[확정+알림] {candidate['resource_type']} {candidate['resource_id']}")

    return all_candidates


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description="Azure 미사용 리소스 탐지기")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        candidates = asyncio.run(detect_unused(dry_run=args.dry_run))
        print(json.dumps(candidates, indent=2, ensure_ascii=False))
        if not candidates:
            print("\n[정보] 미사용 리소스 후보가 없습니다.")
    except ClientAuthenticationError as error:
        print("[ERROR] Azure 인증 실패", file=sys.stderr)
        print("확인할 것: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET", file=sys.stderr)
        print(error, file=sys.stderr)
        sys.exit(1)
    except HttpResponseError as error:
        print("[ERROR] Azure API 호출 실패 (권한 부족 가능성 확인)", file=sys.stderr)
        print(error, file=sys.stderr)
        sys.exit(1)
    except RuntimeError as error:
        print("[ERROR] 미사용 리소스 탐지기 실행 실패", file=sys.stderr)
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
