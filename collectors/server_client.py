"""
중앙 서버(EC2 FastAPI) 전송용 HTTP 클라이언트.
- SERVER_URL은 .env 또는 셸 환경변수에서 읽는다 (없으면 localhost).
- 세 클라우드 수집기(aws/gcp/azure)가 공통으로 쓸 수 있게 최소 기능만 둔다.
"""
import os

import requests

# python-dotenv가 있으면 .env를 읽고, 없으면 셸 환경변수/기본값으로 폴백
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
TIMEOUT = 10  # 초


def check_health():
    """서버가 살아있는지 확인. 실패하면 예외를 던진다."""
    r = requests.get(f"{SERVER_URL}/health", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def post_resource(payload):
    """자원 메트릭 1건 전송. Response 객체를 그대로 반환한다."""
    return requests.post(f"{SERVER_URL}/resources", json=payload, timeout=TIMEOUT)


def post_cost(payload):
    """비용 레코드 1건 전송. Response 객체를 그대로 반환한다."""
    return requests.post(f"{SERVER_URL}/costs", json=payload, timeout=TIMEOUT)
