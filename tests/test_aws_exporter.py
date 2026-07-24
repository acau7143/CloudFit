import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collectors.aws_exporter import to_common_record, to_common_cost_record


# --- 자원 레코드 ---

def test_to_common_record_returns_required_fields():
    record = to_common_record("i-test", 15.3, 45.2, 60.1, "t3.micro")
    assert record["cloud"] == "AWS"
    assert record["cpu_avg"] == 15.3
    assert record["vcpu"] == 2


def test_to_common_record_handles_none_memory():
    record = to_common_record("i-test", 15.3, None, None, "t3.micro")
    assert record["memory_avg"] is None
    assert record["disk_avg"] is None


def test_to_common_record_unknown_instance_type_returns_none_spec():
    record = to_common_record("i-test", 10.0, 20.0, 30.0, "m5.giant-unknown")
    assert record["vcpu"] is None
    assert record["ram_gb"] is None


# --- 비용 레코드 (3주차, decisions/0002) ---

def test_to_common_cost_record_fields():
    record = to_common_cost_record(
        "2026-07-20", "0.012345", "USD", "Amazon Elastic Compute Cloud - Compute"
    )
    assert record["cloud"] == "AWS"
    assert record["date"] == "2026-07-20"
    assert record["cost_usd"] == 0.012345
    assert record["currency"] == "USD"
    assert record["service"] == "Amazon Elastic Compute Cloud - Compute"
    assert record["granularity"] == "DAILY"


def test_cost_usd_is_float():
    record = to_common_cost_record("2026-07-20", "1.5", "USD", "EC2")
    assert isinstance(record["cost_usd"], float)
    assert record["cost_usd"] == 1.5
