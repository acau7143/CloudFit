"""
Slack Webhook 알림 공용 모듈.

A(AWS), C(GCP) 탐지기도 이 함수를 그대로 import해서 쓴다.
자기 클라우드 탐지기에서 알림 보낼 때 새로 구현할 필요 없음:

    from server.notifier import send_slack_alert
    send_slack_alert("[미사용 리소스 발견] AWS", "볼륨 vol-0123... 30일 이상 미연결")
"""

import os
import sys
from pathlib import Path

import requests

# server/notifier.py 기준 프로젝트 루트(.env 있는 곳)를 명시적으로 지정해서 읽는다.
# dotenv가 없는 환경에서도 셸 환경변수만으로 동작 가능하게 try/except로 방어.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def send_slack_alert(title: str, message: str, color: str = "#ff0000") -> int:
    """Slack 채널로 알림을 보낸다.

    title: 알림 제목 (예: '[미사용 리소스 발견] AWS')
    message: 본문
    color: Slack attachment 색상 (기본 빨강)

    반환: HTTP 상태 코드.
    Webhook URL이 설정 안 돼 있거나 전송에 실패하면 예외를 던지지 않고 0을 반환한다
    (팀 환경마다 .env 세팅이 다를 수 있고, Slack 장애 때문에 탐지기 자체가
    죽으면 안 되기 때문).
    """
    if not SLACK_WEBHOOK_URL:
        print(
            f"[WARN] SLACK_WEBHOOK_URL이 설정되지 않았습니다. 알림을 보내지 않습니다. "
            f"({title}: {message})",
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
