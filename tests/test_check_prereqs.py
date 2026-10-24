import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "collectors"))

import check_prereqs as cp
from check_prereqs import OK, WARN, FAIL

ENV_KEYS = [
    "AWS_REGION", "AWS_INSTANCE_ID", "GCP_PROJECT_ID", "GCP_ZONE", "GCP_INSTANCE_NAME",
    "GCP_BILLING_ACCOUNT_ID", "DB_PASSWORD", "DATABASE_URL", "SERVER_URL",
] + cp.AZURE_KEYS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def statuses(results):
    return [r[0] for r in results]


# --- 판정 로직 ---

def test_check_env_fails_and_lists_all_missing_keys():
    status, _, detail = cp.check_env("x", ["AWS_REGION", "AWS_INSTANCE_ID"])
    assert status == FAIL
    assert "AWS_REGION" in detail and "AWS_INSTANCE_ID" in detail


def test_check_env_ok_when_all_set(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_INSTANCE_ID", "i-abc")
    assert cp.check_env("x", ["AWS_REGION", "AWS_INSTANCE_ID"])[0] == OK


def test_metric_results_cpu_missing_is_fail_but_agent_metrics_are_warn():
    hints = {"cpu": "c", "memory": "m", "disk": "d"}
    assert statuses(cp.metric_results(None, 10.0, 20.0, hints)) == [FAIL, OK, OK]
    assert statuses(cp.metric_results(10.0, None, None, hints)) == [OK, WARN, WARN]
    assert statuses(cp.metric_results(10.0, 20.0, 30.0, hints)) == [OK, OK, OK]


def test_exit_code_only_fail_counts():
    assert cp.exit_code([(OK, "a", ""), (WARN, "b", "")]) == 0
    assert cp.exit_code([(OK, "a", ""), (FAIL, "b", "")]) == 1


def test_safe_converts_exception_to_fail_and_keeps_going():
    def boom():
        raise PermissionError("AccessDenied")
    status, name, detail = cp._safe("권한 점검", boom)
    assert status == FAIL and name == "권한 점검"
    assert "PermissionError" in detail and "AccessDenied" in detail


def test_safe_reports_missing_package():
    def missing():
        raise ImportError("No module named 'boto3'")
    status, _, detail = cp._safe("x", missing)
    assert status == FAIL and "boto3" in detail


# --- 서버 연결 ---

class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_server_health_ok(monkeypatch):
    import requests
    monkeypatch.setenv("SERVER_URL", "http://example.test:8000")
    monkeypatch.setattr(requests, "get", lambda url, timeout: _Resp(200))
    status, _, detail = cp.check_server_health()
    assert status == OK and "example.test" in detail


def test_server_health_fail_on_connection_error(monkeypatch):
    import requests

    def refuse(url, timeout):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "get", refuse)
    status, _, detail = cp.check_server_health()
    assert status == FAIL and "SERVER_URL" in detail


def test_server_health_fail_on_bad_status(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, timeout: _Resp(500))
    assert cp.check_server_health()[0] == FAIL


# --- 클라우드별 점검 흐름 ---

def test_each_cloud_stops_early_with_missing_env():
    for func in (cp.aws_checks, cp.gcp_checks, cp.azure_checks):
        results = func()
        assert len(results) == 1 and results[0][0] == FAIL


def test_aws_checks_classify_results(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_INSTANCE_ID", "i-abc")
    monkeypatch.setenv("SERVER_URL", "http://example.test:8000")
    import aws_exporter
    import requests

    class FakeClient:
        def get_caller_identity(self):
            return {}

        def get_cost_and_usage(self, **kwargs):
            raise PermissionError("not allowed")

    monkeypatch.setattr(cp, "_boto3_client", lambda service, region: FakeClient())
    monkeypatch.setattr(aws_exporter, "get_instance_type", lambda iid: "t3.micro")
    # CPU 는 있고 메모리/디스크는 에이전트가 없어서 비어 있는 상황
    monkeypatch.setattr(aws_exporter, "collect_resource_metrics", lambda iid: (12.3, None, None))
    monkeypatch.setattr(requests, "get", lambda url, timeout: _Resp(200))

    results = cp.aws_checks()
    by_name = {r[1]: r[0] for r in results}
    assert by_name["AWS 자격증명"] == OK
    assert by_name["CPU 지표"] == OK
    assert by_name["메모리 지표"] == WARN
    assert by_name["디스크 지표"] == WARN
    assert by_name["비용 조회 (Cost Explorer)"] == WARN  # 비용이 안 돼도 자원 수집은 가능
    assert cp.exit_code(results) == 0


def test_aws_checks_stop_when_credentials_invalid(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_INSTANCE_ID", "i-abc")

    class NoCreds:
        def get_caller_identity(self):
            raise RuntimeError("Unable to locate credentials")

    monkeypatch.setattr(cp, "_boto3_client", lambda service, region: NoCreds())
    results = cp.aws_checks()
    assert results[1][0] == FAIL
    assert cp.exit_code(results) == 1
    assert all(r[1] != "CPU 지표" for r in results)  # 이후 점검은 건너뜀


def test_server_checks_skip_db_when_env_missing(monkeypatch):
    import requests

    def refuse(url, timeout):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "get", refuse)
    results = cp.server_checks()
    names = [r[1] for r in results]
    assert "DB 테이블" not in names
    assert cp.exit_code(results) == 1


def test_main_prints_summary_and_returns_exit_code(monkeypatch, capsys):
    monkeypatch.setitem(cp.CHECKS, "aws", lambda: [(OK, "a", "ok"), (WARN, "b", "warn")])
    assert cp.main(["aws"]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] a - ok" in out and "[WARN] b - warn" in out and "OK 1 / WARN 1 / FAIL 0" in out
