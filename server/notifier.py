import os
import requests

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
