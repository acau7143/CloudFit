"""Grafana 자동 설정(프로비저닝) 파일들이 서로 어긋나지 않는지 확인한다.

패널이 데이터소스를 uid 로 참조하기 때문에 uid·종류·마운트 경로 중 하나만 바뀌어도 새 환경의 대시보드가 비어 보인다.
Grafana 를 실제로 띄우는 검증은 decisions/0015 에 기록했고, 여기서는 그 설정이 깨지지 않게 파일끼리의 약속만 본다.
(PyYAML 에 의존하지 않도록 필요한 값만 정규식으로 읽는다.)
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _dashboard():
    return json.loads(_text("dashboard/dashboard.json"))


def _datasource_yaml():
    return _text("grafana/provisioning/datasources/postgres.yaml")


def _queries(dash):
    for element in dash["spec"]["elements"].values():
        for q in element["spec"]["data"]["spec"]["queries"]:
            yield q["spec"]["query"]


def test_dashboard_file_is_clean_v2_resource():
    dash = _dashboard()
    assert dash["apiVersion"] == "dashboard.grafana.app/v2"
    assert dash["kind"] == "Dashboard"
    # 파일 프로비저닝은 인스턴스마다 다른 값(버전 번호, 작성자, 생성 시각 등)이 metadata 에 있으면 안 된다.
    assert set(dash["metadata"]) == {"name"}
    assert len(dash["spec"]["elements"]) == 8


def test_every_panel_references_the_provisioned_datasource_uid():
    uid = re.search(r"^\s*uid:\s*(\S+)", _datasource_yaml(), re.M).group(1)
    refs = {q["datasource"]["name"] for q in _queries(_dashboard())}
    assert refs == {uid}


def test_provisioned_datasource_type_matches_panel_queries():
    ds_type = re.search(r"^\s*type:\s*(\S+)", _datasource_yaml(), re.M).group(1)
    groups = {q["group"] for q in _queries(_dashboard())}
    assert groups == {ds_type}


def test_datasource_connects_to_compose_db_service():
    text = _datasource_yaml()
    compose = _text("docker-compose.yml")
    assert re.search(r"^\s*url:\s*db:5432\s*$", text, re.M)
    assert "POSTGRES_USER: finops" in compose and re.search(r"^\s*user:\s*finops\s*$", text, re.M)
    assert "POSTGRES_DB: finops_db" in compose and "database: finops_db" in text
    # 비밀번호는 파일에 적지 않고 환경변수로 받는다.
    assert "password: ${DB_PASSWORD}" in text


def test_override_mounts_match_provider_path_and_pins_image():
    override = _text("docker-compose.grafana.yml")
    provider = _text("grafana/provisioning/dashboards/cloudfit.yaml")
    assert "./grafana/provisioning:/etc/grafana/provisioning:ro" in override
    assert "./dashboard:/etc/grafana/dashboards:ro" in override
    assert re.search(r"path:\s*/etc/grafana/dashboards\s*$", provider, re.M)
    image = re.search(r"image:\s*(\S+)", override).group(1)
    assert image.startswith("grafana/grafana:") and not image.endswith(":latest")
    assert "DB_PASSWORD: ${DB_PASSWORD}" in override
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}" in override


def test_base_compose_does_not_touch_existing_grafana():
    """운영처럼 이미 수동으로 설정한 Grafana 가 있는 서버에서 그냥 `docker compose up` 을 해도 달라지지 않아야 한다.

    같은 uid 의 데이터소스가 다른 이름으로 있으면 프로비저닝 오류로 Grafana 가 시작하지 못한다(실제 확인).
    """
    compose = _text("docker-compose.yml")
    assert "grafana/provisioning" not in compose
    assert "/etc/grafana/dashboards" not in compose


def test_installer_uses_override_and_has_opt_out():
    script = _text("scripts/install_server.sh")
    assert "docker-compose.grafana.yml" in script
    assert "--no-grafana-provision" in script
