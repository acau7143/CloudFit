"""
AWS 미사용 리소스 탐지 모듈 (9주차)
- 미연결 EBS 볼륨: describe_volumes(status=available)
- 미연결 Elastic IP: describe_addresses()에서 AssociationId 없는 것
- 탐지 결과는 collectors/server_client.py를 통해 중앙 서버(/unused-resources)로 전송
- 두 번 연속(재탐지) 발견된 것만 server/notifier.py를 통해 Slack 알림을 보낸다
  (방금 생성한 리소스가 1회성으로 잡혀서 바로 알림 가는 오탐 방지)
"""
import os
import sys
import json

import boto3

from server_client import post_unused_resource

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "server"))
from notifier import send_slack_alert

REGION = "ap-northeast-2"
ec2 = boto3.client("ec2", region_name=REGION)

# 직전 실행의 탐지 결과를 저장해두는 로컬 상태 파일 (이 EC2 안에서만 유효)
STATE_FILE = os.path.join(os.path.dirname(__file__), ".aws_unused_state.json")


def detect_unused_volumes():
    """상태가 'available'(인스턴스 미연결)인 EBS 볼륨을 찾는다."""
    resp = ec2.describe_volumes(
        Filters=[{"Name": "status", "Values": ["available"]}]
    )
    results = []
    for vol in resp.get("Volumes", []):
        results.append({
            "cloud": "AWS",
            "resource_type": "volume",
            "resource_id": vol["VolumeId"],
            "reason": f"인스턴스 미연결 (생성일: {vol['CreateTime'].date()}, 크기: {vol['Size']}GB)",
        })
    return results


def detect_unused_ips():
    """인스턴스에 연결되지 않은(AssociationId 없는) Elastic IP를 찾는다."""
    resp = ec2.describe_addresses()
    results = []
    for addr in resp.get("Addresses", []):
        if "AssociationId" not in addr:
            results.append({
                "cloud": "AWS",
                "resource_type": "ip",
                "resource_id": addr.get("AllocationId", addr.get("PublicIp")),
                "reason": f"인스턴스 미연결 Elastic IP ({addr.get('PublicIp')})",
            })
    return results


def _resource_key(item: dict) -> str:
    """resource_type + resource_id로 고유 키를 만든다 (볼륨/IP가 같은 ID값을 가질 가능성 대비)."""
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


def detect_unused(dry_run: bool = False):
    """미사용 리소스를 전부 탐지해서 반환한다. dry_run=False면 서버 전송 + 재탐지 시 Slack 알림까지 수행한다."""
    unused = detect_unused_volumes() + detect_unused_ips()

    if dry_run:
        return unused

    ok, fail = 0, 0
    for item in unused:
        r = post_unused_resource(item)
        if r.status_code in (200, 201):
            ok += 1
        else:
            fail += 1
            print(f"[전송 실패] {item['resource_type']} {item['resource_id']} → {r.status_code} {r.text}")
    print(f"[결과] 성공 {ok} / 실패 {fail} (총 {len(unused)}건)")

    # [9주차] 재탐지 로직: 이번 탐지 결과와 직전 탐지 결과 둘 다에 있는 것만 알림 대상
    current_ids = {_resource_key(i) for i in unused}
    previous_ids = load_previous_ids()
    repeated_ids = current_ids & previous_ids
    repeated_items = [i for i in unused if _resource_key(i) in repeated_ids]

    if repeated_items:
        lines = [f"- {i['resource_type']} {i['resource_id']}: {i['reason']}" for i in repeated_items]
        send_slack_alert(
            "[미사용 리소스 발견] AWS",
            f"{len(repeated_items)}건 (재탐지 확인됨)\n" + "\n".join(lines),
        )
    else:
        print("[정보] 재탐지된 리소스 없음 - 알림 스킵 (신규 탐지분은 다음 실행에서 재확인)")

    save_current_ids(current_ids)

    return unused


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AWS 미사용 리소스 탐지기")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="서버 전송 없이 탐지 결과만 출력한다.",
    )
    args = parser.parse_args()

    result = detect_unused(dry_run=args.dry_run)

    if args.dry_run:
        print("=== UNUSED RESOURCES ===")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if not result:
            print("\n[정보] 현재 미사용으로 탐지된 리소스가 없습니다.")
