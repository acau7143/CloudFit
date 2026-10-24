import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collectors import cloud_config
from collectors import aws_exporter


ALL_KEYS = [
    "AWS_REGION", "AWS_INSTANCE_ID", "AWS_DISK_DEVICE", "AWS_DISK_FSTYPE",
    "GCP_PROJECT_ID", "GCP_ZONE", "GCP_REGION", "GCP_INSTANCE_NAME",
    "GCP_BILLING_ACCOUNT_ID", "GCP_DISK_DEVICE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """로컬 .env나 셸 환경변수가 테스트 결과에 섞이지 않게 관련 키를 모두 지운다."""
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


# --- 필수/선택 값 읽기 ---

def test_require_env_lists_all_missing_keys_at_once():
    with pytest.raises(cloud_config.ConfigError) as exc:
        cloud_config.require_env("AWS_REGION", "AWS_INSTANCE_ID")
    assert "AWS_REGION" in str(exc.value)
    assert "AWS_INSTANCE_ID" in str(exc.value)


def test_empty_string_counts_as_missing(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "")
    with pytest.raises(cloud_config.ConfigError):
        cloud_config.aws_region()


def test_require_env_returns_values(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    assert cloud_config.require_env("AWS_REGION") == {"AWS_REGION": "us-east-2"}


def test_exit_on_config_error_exits_with_code_2(capsys):
    with pytest.raises(SystemExit) as exc:
        cloud_config.exit_on_config_error(cloud_config.aws_region)
    assert exc.value.code == 2
    assert "AWS_REGION" in capsys.readouterr().err


# --- AWS ---

def test_aws_instance_id_cli_value_wins_over_env(monkeypatch):
    monkeypatch.setenv("AWS_INSTANCE_ID", "i-from-env")
    assert cloud_config.aws_instance_id("i-from-cli") == "i-from-cli"
    assert cloud_config.aws_instance_id(None) == "i-from-env"


def test_aws_instance_id_missing_raises():
    with pytest.raises(cloud_config.ConfigError):
        cloud_config.aws_instance_id(None)


def test_aws_disk_dimensions_defaults_match_previous_hardcoded_values():
    dims = {d["Name"]: d["Value"] for d in cloud_config.aws_disk_dimensions()}
    assert dims == {"path": "/", "device": "nvme0n1p1", "fstype": "xfs"}


def test_aws_disk_dimensions_can_be_overridden(monkeypatch):
    monkeypatch.setenv("AWS_DISK_DEVICE", "xvda1")
    monkeypatch.setenv("AWS_DISK_FSTYPE", "ext4")
    dims = {d["Name"]: d["Value"] for d in cloud_config.aws_disk_dimensions()}
    assert dims["device"] == "xvda1"
    assert dims["fstype"] == "ext4"


def test_collect_resource_metrics_uses_configured_disk_dimensions(monkeypatch):
    monkeypatch.setenv("AWS_DISK_DEVICE", "xvda1")
    seen = {}

    def fake_average(namespace, metric_name, dimensions):
        seen[metric_name] = dimensions
        return 1.0

    monkeypatch.setattr(aws_exporter, "_get_metric_average", fake_average)
    aws_exporter.collect_resource_metrics("i-abc")

    disk_dims = {d["Name"]: d["Value"] for d in seen["disk_used_percent"]}
    assert disk_dims["InstanceId"] == "i-abc"
    assert disk_dims["device"] == "xvda1"


class _FakeEc2:
    def __init__(self, response=None, error=None):
        self._response, self._error = response, error

    def describe_instance_types(self, InstanceTypes):
        if self._error:
            raise self._error
        return self._response


def test_get_instance_specs_uses_ec2_api(monkeypatch):
    fake = _FakeEc2({"InstanceTypes": [{
        "VCpuInfo": {"DefaultVCpus": 4},
        "MemoryInfo": {"SizeInMiB": 16384},
    }]})
    monkeypatch.setattr(aws_exporter, "_ec2", lambda: fake)
    assert aws_exporter.get_instance_specs("m5.xlarge") == {"vcpu": 4, "ram_gb": 16.0}


def test_get_instance_specs_falls_back_to_table_when_api_fails(monkeypatch):
    monkeypatch.setattr(aws_exporter, "_ec2", lambda: _FakeEc2(error=RuntimeError("AccessDenied")))
    assert aws_exporter.get_instance_specs("t3.micro") == {"vcpu": 2, "ram_gb": 1}
    assert aws_exporter.get_instance_specs("m5.giant-unknown") == {}


def test_to_common_record_prefers_given_specs():
    record = aws_exporter.to_common_record(
        "i-test", 1.0, 2.0, 3.0, "m5.xlarge", {"vcpu": 4, "ram_gb": 16.0}
    )
    assert record["vcpu"] == 4
    assert record["ram_gb"] == 16.0


# --- GCP ---

def test_gcp_region_derived_from_zone(monkeypatch):
    monkeypatch.setenv("GCP_ZONE", "asia-northeast3-a")
    assert cloud_config.gcp_region() == "asia-northeast3"


def test_gcp_region_explicit_override(monkeypatch):
    monkeypatch.setenv("GCP_ZONE", "asia-northeast3-a")
    monkeypatch.setenv("GCP_REGION", "europe-west1")
    assert cloud_config.gcp_region() == "europe-west1"


def test_gcp_required_values_missing_raise():
    for func in (
        cloud_config.gcp_project_id,
        cloud_config.gcp_zone,
        cloud_config.gcp_instance_name,
        cloud_config.gcp_billing_account_id,
    ):
        with pytest.raises(cloud_config.ConfigError):
            func()


def test_gcp_disk_device_default_matches_previous_hardcoded_value(monkeypatch):
    assert cloud_config.gcp_disk_device() == "/dev/sda1"
    monkeypatch.setenv("GCP_DISK_DEVICE", "/dev/sdb")
    assert cloud_config.gcp_disk_device() == "/dev/sdb"
