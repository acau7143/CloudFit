"""GCP·Azure 수집기의 --costs 분리 테스트 (decisions/0003: 자원 5분 / 비용 하루 한 번).

AWS 수집기와 같은 규칙: --costs 가 없으면 자원만, 있으면 비용까지 수집·전송한다.
"""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "collectors"))

import gcp_exporter as gcp
from collectors import azure_exporter as azure

GCP_KEYS = ["GCP_PROJECT_ID", "GCP_ZONE", "GCP_INSTANCE_NAME", "GCP_BILLING_ACCOUNT_ID"]


# ---------------------------------------------------------------- GCP

@pytest.fixture
def gcp_calls(monkeypatch):
    for key, value in zip(GCP_KEYS, ["proj-1", "asia-northeast3-a", "vm-1", "AAAAAA-BBBBBB-CCCCCC"]):
        monkeypatch.setenv(key, value)

    calls = {"collect_cost": [], "resource": [], "cost": [], "metric_instance_ids": []}

    def metric(records):
        def fake(project, *args, instance_id=None, **kwargs):
            calls["metric_instance_ids"].append(instance_id)
            return records
        return fake

    monkeypatch.setattr(gcp, "collect_cpu", metric([{"timestamp": "t", "provider": "gcp", "instance_id": "123", "cpu_percent": 10.0}]))
    monkeypatch.setattr(gcp, "collect_memory", metric([{"memory_percent": 40.0}]))
    monkeypatch.setattr(gcp, "collect_disk", metric([{"disk_percent": 50.0}]))
    monkeypatch.setattr(
        gcp, "get_instance",
        lambda p, z, n: {"id": 5207434110382276471, "machineType": "https://x/zones/z/machineTypes/e2-micro"},
    )
    monkeypatch.setattr(gcp, "get_machine_specs", lambda p, z, t: {"vcpu": 2, "ram_gb": 1.0})

    def fake_collect_cost(project, billing, machine_type="e2-micro"):
        calls["collect_cost"].append((project, billing))
        return [gcp.to_common_cost_record("2026-10-23", 0.3, "Compute Engine"),
                gcp.to_common_cost_record("2026-10-23", 0.07, "Networking")]

    monkeypatch.setattr(gcp, "collect_cost", fake_collect_cost)
    monkeypatch.setattr(gcp, "send_resource_to_server", lambda r: calls["resource"].append(r) or True)
    monkeypatch.setattr(gcp, "send_cost_to_server", lambda r: calls["cost"].append(r) or True)
    return calls


def test_gcp_default_run_sends_resource_only(gcp_calls):
    gcp.main([])
    assert len(gcp_calls["resource"]) == 1
    assert gcp_calls["collect_cost"] == []      # BigQuery 를 조회하지 않는다
    assert gcp_calls["cost"] == []


def test_gcp_costs_flag_sends_resource_and_costs(gcp_calls):
    gcp.main(["--costs"])
    assert len(gcp_calls["resource"]) == 1
    assert gcp_calls["collect_cost"] == [("proj-1", "AAAAAA-BBBBBB-CCCCCC")]
    assert len(gcp_calls["cost"]) == 2


def test_gcp_dry_run_prints_both_and_sends_nothing(gcp_calls, capsys):
    gcp.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "=== 비용 데이터 수집 테스트 ===" in out and "Compute Engine" in out
    assert gcp_calls["resource"] == [] and gcp_calls["cost"] == []
    assert len(gcp_calls["collect_cost"]) == 1


def test_gcp_resource_only_run_does_not_need_billing_account(gcp_calls, monkeypatch):
    monkeypatch.delenv("GCP_BILLING_ACCOUNT_ID")
    gcp.main([])                                 # 오류 없이 끝나야 한다
    assert len(gcp_calls["resource"]) == 1


@pytest.mark.parametrize("argv", [["--costs"], ["--dry-run"]])
def test_gcp_cost_runs_require_billing_account(gcp_calls, monkeypatch, capsys, argv):
    monkeypatch.delenv("GCP_BILLING_ACCOUNT_ID")
    with pytest.raises(SystemExit) as exc:
        gcp.main(argv)
    assert exc.value.code == 2
    assert "GCP_BILLING_ACCOUNT_ID" in capsys.readouterr().err
    assert gcp_calls["resource"] == []


def test_gcp_unknown_flag_is_rejected(gcp_calls):
    with pytest.raises(SystemExit):
        gcp.main(["--bogus"])                    # 모르는 옵션이 조용히 무시되면 안 된다


# ---------------------------------------------------------------- Azure

@pytest.fixture
def azure_calls(monkeypatch):
    calls = {"collect_cost": 0, "resource": [], "cost": []}
    raw = {
        "cloud": "Azure", "instance_id": "vm-1", "timestamp": "2026-10-24T00:00:00Z",
        "cpu_avg": 1.0, "memory_avg": 40.0, "disk_avg": 20.0,
        "instance_type": "Standard_B2ats_v2", "vcpu": 2, "ram_gb": 1.0, "cost_monthly": None,
    }
    monkeypatch.setattr(azure, "collect_resource_metrics", lambda: raw)
    monkeypatch.setattr(azure, "send_resource_to_server", lambda r: calls["resource"].append(r) or True)
    monkeypatch.setattr(azure, "load_config", lambda: {"subscription_id": "sub", "resource_group": "rg"})
    monkeypatch.setattr(azure, "build_credential", lambda config: object())
    monkeypatch.setattr(azure, "CostManagementClient", lambda credential: object())

    def fake_collect_cost(client, subscription_id, resource_group):
        calls["collect_cost"] += 1
        return [{"Cost": 1.5, "UsageDate": 20261023, "ServiceName": "Virtual Network", "Currency": "USD"}]

    monkeypatch.setattr(azure, "collect_cost", fake_collect_cost)
    monkeypatch.setattr(azure, "send_cost_to_server", lambda r: calls["cost"].append(r) or True)
    return calls


def test_azure_default_run_sends_resource_only(azure_calls):
    azure.run_send()
    assert len(azure_calls["resource"]) == 1
    assert azure_calls["collect_cost"] == 0     # Cost Management API 를 호출하지 않는다 (분당 4회 제한)
    assert azure_calls["cost"] == []


def test_azure_costs_flag_sends_resource_and_costs(azure_calls):
    azure.run_send(include_costs=True)
    assert len(azure_calls["resource"]) == 1
    assert azure_calls["collect_cost"] == 1
    assert len(azure_calls["cost"]) == 1
    assert azure_calls["cost"][0]["cloud"] == "Azure" and azure_calls["cost"][0]["cost_usd"] == 1.5


def test_azure_main_routes_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(azure, "run_send", lambda include_costs=False: seen.append(("send", include_costs)))
    monkeypatch.setattr(azure, "run_dry_run", lambda: seen.append(("dry", None)))
    azure.main([])
    azure.main(["--costs"])
    azure.main(["--dry-run"])
    assert seen == [("send", False), ("send", True), ("dry", None)]


# ---- 대상 VM 으로 좁히기: 프로젝트에 VM 이 여러 대여도 다른 VM 의 지표가 섞이지 않아야 한다 ----

def test_gcp_metrics_are_queried_for_the_target_instance_only(gcp_calls):
    gcp.main(["--costs"])
    # cpu, memory, disk 세 번 모두 같은 숫자 instance id 로 좁혀서 조회
    assert gcp_calls["metric_instance_ids"] == ["5207434110382276471"] * 3


def test_gcp_record_uses_the_api_instance_id_not_the_first_metric_record(gcp_calls):
    gcp.main([])
    # 다른 VM 의 지표가 첫 레코드("123")여도 레코드 id 는 대상 VM 의 id 여야 한다
    assert gcp_calls["resource"][0]["instance_id"] == "5207434110382276471"


class _Capture:
    """list_time_series 에 전달된 요청을 가로채서 필터 문자열을 모은다."""
    def __init__(self, monkeypatch):
        self.filters = []
        monkeypatch.setattr(gcp.monitoring_v3, "MetricServiceClient", lambda: object())
        monkeypatch.setattr(
            gcp, "_list_time_series_with_retry",
            lambda client, request, max_retries=3: self.filters.append(request["filter"]) or [],
        )


@pytest.mark.parametrize("func", ["collect_cpu", "collect_memory", "collect_disk"])
def test_gcp_collect_filter_includes_instance_label_when_given(monkeypatch, func):
    cap = _Capture(monkeypatch)
    getattr(gcp, func)("proj-1", instance_id="999")
    assert 'resource.labels.instance_id="999"' in cap.filters[0]


@pytest.mark.parametrize("func", ["collect_cpu", "collect_memory", "collect_disk"])
def test_gcp_collect_filter_has_no_instance_label_by_default(monkeypatch, func):
    cap = _Capture(monkeypatch)
    getattr(gcp, func)("proj-1")
    assert "resource.labels.instance_id" not in cap.filters[0]    # 기존 동작 유지(호환)
