import os
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


def send_slack_alert(title: str, message: str, color: str = "#ff0000"):
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
