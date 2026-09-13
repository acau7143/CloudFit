"""
Slack Webhook 알림 공용 모듈.

A(AWS), C(GCP) 탐지기도 이 함수를 그대로 import해서 쓴다.
자기 클라우드 탐지기에서 알림 보낼 때 새로 구현할 필요 없음:

    from server.notifier import send_slack_alert
    send_slack_alert("[미사용 리소스 발견] AWS", "볼륨 vol-0123... 30일 이상 미연결")
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


def send_slack_alert(title: str, message: str, color: str = "#ff0000") -> int:
    """Slack 채널로 알림을 보낸다.

    title: 알림 제목 (예: '[미사용 리소스 발견] AWS')
    message: 본문
    color: Slack attachment 색상 (기본 빨강)

    반환: HTTP 상태 코드.
    Webhook URL이 설정 안 돼 있으면 요청을 보내지 않고 0을 반환한다
    (팀 환경마다 .env 세팅이 다를 수 있어서, 미설정 상태에서도 탐지기 자체는
    죽지 않고 계속 동작해야 하기 때문).
    """
    if not SLACK_WEBHOOK_URL:
        print(
            "[WARN] SLACK_WEBHOOK_URL이 설정되지 않았습니다. 알림을 보내지 않습니다.",
            file=sys.stderr,
        )
        return 0

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
            }
        ]
    }
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        response.raise_for_status()
        return response.status_code
    except requests.exceptions.RequestException as error:
        print(f"[FAIL] Slack 알림 전송 실패: {error}", file=sys.stderr)
        return 0
