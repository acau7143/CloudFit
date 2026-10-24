"""
GCP 미사용 리소스(디스크 / 공인 IP) 탐지기.

판정 기준:
- 디스크: users 필드가 비어있으면(어떤 인스턴스에도 안 붙어있으면) 미사용
- 공인 IP: RESERVED 상태인데 users가 없으면 미사용

[10주차] AWS(fix(aws-collector))와 동일하게, 재탐지(연속 2회 탐지) 확인된 것만
Slack 알림을 보낸다. 공용 모듈(unused_resource_common.py) 없이 이 파일 안에서
직접 처리한다 - server_client.py/notifier.py가 이 브랜치엔 없어서 gcp_exporter.py의
requests.post 패턴을 그대로 따름.
"""
import argparse
import json
import os

import requests
from dotenv import load_dotenv
from google.cloud import compute_v1

load_dotenv()

PROJECT_ID = "project-3f80ed2e-f0f6-4855-b15"
REGION = "asia-northeast3"
ZONE = "asia-northeast3-a"

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# 직전 실행의 탐지 결과를 저장해두는 로컬 상태 파일 (이 GCP VM 안에서만 유효)
STATE_FILE = os.path.join(os.path.dirname(__file__), ".gcp_unused_state.json")


def find_unused_disks(project_id: str, zone: str) -> list[dict]:
    """users 필드가 비어있으면(어떤 인스턴스에도 안 붙어있으면) 미사용 디스크"""
    client = compute_v1.DisksClient()
    unused = []
    for disk in client.list(project=project_id, zone=zone):
        if not disk.users:
            unused.append({
                "cloud": "GCP",
                "resource_type": "disk",
                "resource_id": disk.name,
                "reason": f"어떤 인스턴스에도 연결되어 있지 않음 (size={disk.size_gb}GB)",
            })
    return unused


def find_unused_ips(project_id: str, region: str) -> list[dict]:
    """RESERVED 상태인데 users가 없는 정적 IP는 미사용"""
    client = compute_v1.AddressesClient()
    unused = []
    for addr in client.list(project=project_id, region=region):
        if addr.status == "RESERVED" and not addr.users:
            unused.append({
                "cloud": "GCP",
                "resource_type": "ip",
                "resource_id": addr.name,
                "reason": f"예약됐지만 아무 리소스에도 안 쓰이고 있음 (address={addr.address})",
            })
    return unused


def _resource_key(item: dict) -> str:
    """resource_type + resource_id로 고유 키를 만든다."""
    return f"{item['resource_type']}:{item['resource_id']}"


def load_previous_ids() -> set:
    """직전 실행에서 탐지됐던 리소스 키 목록을 불러온다. 첫 실행이면 빈 집합."""
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_current_ids(ids: set):
    """이번 실행의 탐지 키 목록을 저장한다 - 다음 실행이 이걸 '직전 결과'로 사용함."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False)


def post_unused_resource(item: dict) -> bool:
    """중앙 서버 /unused-resources 엔드포인트로 탐지 결과 전송."""
    try:
        resp = requests.post(f"{SERVER_URL}/unused-resources", json=item, timeout=5)
        if resp.status_code in (200, 201):
            return True
        print(f"[전송 실패] {item['resource_type']} {item['resource_id']} → {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[전송 실패] {item['resource_type']} {item['resource_id']} → 예외: {e}")
        return False


def send_slack_alert(title: str, message: str, color: str = "#ff0000"):
    """server/notifier.py가 이 브랜치엔 없어서 AWS 쪽 로직을 그대로 인라인으로 둔다."""
    if not SLACK_WEBHOOK_URL:
        print(f"[알림 스킵 - SLACK_WEBHOOK_URL 없음] {title}: {message}")
        return None
    payload = {
        "attachments": [{
            "color": color,
            "title": title,
            "text": message,
        }]
    }
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
    resp.raise_for_status()
    return resp.status_code


def detect_unused(dry_run: bool = False):
    """미사용 리소스를 전부 탐지해서 반환한다. dry_run=False면 서버 전송 + 재탐지 시 Slack 알림까지 수행한다."""
    unused = find_unused_disks(PROJECT_ID, ZONE) + find_unused_ips(PROJECT_ID, REGION)

    if dry_run:
        return unused

    ok, fail = 0, 0
    for item in unused:
        if post_unused_resource(item):
            ok += 1
        else:
            fail += 1
    print(f"[결과] 성공 {ok} / 실패 {fail} (총 {len(unused)}건)")

    # [10주차] 재탐지 로직: 이번 탐지 결과와 직전 탐지 결과 둘 다에 있는 것만 알림 대상
    current_ids = {_resource_key(i) for i in unused}
    previous_ids = load_previous_ids()
    repeated_ids = current_ids & previous_ids
    repeated_items = [i for i in unused if _resource_key(i) in repeated_ids]

    if repeated_items:
        lines = [f"- {i['resource_type']} {i['resource_id']}: {i['reason']}" for i in repeated_items]
        send_slack_alert(
            "[미사용 리소스 발견] GCP",
            f"{len(repeated_items)}건 (재탐지 확인됨)\n" + "\n".join(lines),
        )
    else:
        print("[정보] 재탐지된 리소스 없음 - 알림 스킵 (신규 탐지분은 다음 실행에서 재확인)")

    save_current_ids(current_ids)

    return unused


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GCP 미사용 리소스 탐지")
    parser.add_argument("--dry-run", action="store_true", help="서버 전송 없이 조회만")
    args = parser.parse_args()

    result = detect_unused(dry_run=args.dry_run)

    if args.dry_run:
        print("=== UNUSED RESOURCES (dry-run, 서버 전송 안 함) ===")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if not result:
            print("\n[정보] 현재 미사용으로 탐지된 리소스가 없습니다.")
