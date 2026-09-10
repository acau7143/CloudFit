import argparse
import os
import requests
from dotenv import load_dotenv
from google.cloud import compute_v1

load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")

PROJECT_ID = "project-3f80ed2e-f0f6-4855-b15"
REGION = "asia-northeast3"
ZONE = "asia-northeast3-a"


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


def send_unused_resource_to_server(record: dict) -> bool:
    """gcp_exporter.py의 send_resource_to_server()와 동일한 패턴"""
    try:
        response = requests.post(
            f"{SERVER_URL}/unused-resources",
            json=record,
            timeout=5
        )
        if response.status_code == 201:
            print(f"[OK] 미사용 리소스 저장 성공: {record['resource_type']}/{record['resource_id']}")
            return True
        else:
            print(f"[FAIL] 서버 응답 오류: {response.status_code} {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] 서버 연결 실패: {SERVER_URL} 접속 불가")
        return False
    except Exception as e:
        print(f"[FAIL] 예외 발생: {e}")
        return False


def detect_unused(dry_run: bool = False):
    items = find_unused_disks(PROJECT_ID, ZONE) + find_unused_ips(PROJECT_ID, REGION)

    if not items:
        print("[INFO] GCP 미사용 리소스 없음")
        return

    print(f"[GCP] 미사용 리소스 {len(items)}건 발견")
    for item in items:
        print(f"  - {item['resource_type']}: {item['resource_id']} ({item['reason']})")

    if dry_run:
        print("[DRY-RUN] 서버 전송은 생략")
        return

    ok_count = sum(send_unused_resource_to_server(item) for item in items)
    print(f"[OK] {ok_count}/{len(items)}건 서버 전송 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GCP 미사용 리소스 탐지")
    parser.add_argument("--dry-run", action="store_true", help="서버 전송 없이 조회만")
    args = parser.parse_args()
    detect_unused(dry_run=args.dry_run)
