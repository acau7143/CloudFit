import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "collectors"))

from gcp_exporter import to_common_record


def test_to_common_record_cloud_is_gcp():
    cpu = [{"cpu_percent": 15.3}]
    memory = [{"memory_percent": 45.0}]
    disk = [{"disk_percent": 60.0}]
    record = to_common_record("instance-test", cpu, memory, disk, "e2-micro")
    assert record["cloud"] == "GCP"


def test_to_common_record_averages_cpu_correctly():
    cpu = [{"cpu_percent": 10.0}, {"cpu_percent": 20.0}]
    memory = [{"memory_percent": 40.0}]
    disk = [{"disk_percent": 50.0}]
    record = to_common_record("instance-test", cpu, memory, disk, "e2-micro")
    assert record["cpu_avg"] == 15.0  # (10 + 20) / 2


def test_to_common_record_unknown_machine_type_returns_none_specs():
    cpu = [{"cpu_percent": 10.0}]
    memory = [{"memory_percent": 40.0}]
    disk = [{"disk_percent": 50.0}]
    record = to_common_record("instance-test", cpu, memory, disk, "n1-standard-4")
    assert record["vcpu"] is None
    assert record["ram_gb"] is None


def test_to_common_record_empty_records_returns_none_avg():
    record = to_common_record("instance-test", [], [], [], "e2-micro")
    assert record["cpu_avg"] is None
