import unittest

from collectors.azure_exporter import (
    to_common_cost_record,
    to_common_record,
    to_usd,
)


class TestAzureExporter(unittest.TestCase):

    COMMON_KEYS = {
        "cloud", "instance_id", "timestamp", "cpu_avg", "memory_avg", "disk_avg",
        "instance_type", "vcpu", "ram_gb", "cost_monthly",
    }

    def _raw(self, **overrides):
        """collect_resource_metrics()가 돌려주는 형태 (팀 공통 스키마, 2026-07-25 이후)."""
        raw = {
            "cloud": "Azure",
            "instance_id": "vm-finops-azure-test",
            "timestamp": "2026-07-07T10:19:00Z",
            "cpu_avg": 0.525,
            "memory_avg": 48.29,
            "disk_avg": 10.7,
            "instance_type": "Standard_B2ats_v2",
            "vcpu": 2,
            "ram_gb": 1.0,
            "cost_monthly": None,
        }
        raw.update(overrides)
        return raw

    def test_to_common_record_full_fields(self):
        """
        모든 필드가 공통 레코드에 정상적으로 전달되는지 확인한다.
        """

        record = to_common_record(self._raw())

        self.assertEqual(set(record), self.COMMON_KEYS)
        self.assertEqual(record["cloud"], "Azure")
        self.assertEqual(record["instance_id"], "vm-finops-azure-test")
        self.assertEqual(record["timestamp"], "2026-07-07T10:19:00Z")

        self.assertEqual(record["cpu_avg"], 0.525)
        self.assertEqual(record["memory_avg"], 48.29)
        self.assertEqual(record["disk_avg"], 10.7)

        self.assertEqual(record["instance_type"], "Standard_B2ats_v2")
        self.assertEqual(record["vcpu"], 2)
        self.assertEqual(record["ram_gb"], 1.0)

        self.assertIsNone(record["cost_monthly"])


    def test_to_common_record_handles_none_metrics(self):
        """
        메모리와 디스크 값이 없어도 None 상태로 정상 변환되는지 확인한다.
        """

        record = to_common_record(self._raw(cpu_avg=20.0, memory_avg=None, disk_avg=None))

        self.assertEqual(record["cloud"], "Azure")
        self.assertEqual(record["cpu_avg"], 20.0)
        self.assertIsNone(record["memory_avg"])
        self.assertIsNone(record["disk_avg"])
        self.assertIsNone(record["cost_monthly"])


    def test_to_common_record_preserves_zero_values(self):
        """
        사용률이 0.0인 경우 None으로 바뀌지 않고
        실제 숫자 0.0으로 유지되는지 확인한다.
        """

        record = to_common_record(self._raw(cpu_avg=0.0, memory_avg=0.0, disk_avg=0.0))

        self.assertEqual(record["cpu_avg"], 0.0)
        self.assertEqual(record["memory_avg"], 0.0)
        self.assertEqual(record["disk_avg"], 0.0)
        self.assertIsNotNone(record["cpu_avg"])


    def test_internal_fields_are_removed(self):
        """
        Azure 내부 처리용 필드(metric_name, region 등)가
        공통 레코드에는 포함되지 않는지 확인한다.
        """

        raw = self._raw(metric_name="Percentage CPU", region="koreacentral", resource_type="vm")

        record = to_common_record(raw)

        self.assertNotIn("metric_name", record)
        self.assertNotIn("region", record)
        self.assertNotIn("resource_type", record)
        self.assertEqual(set(record), self.COMMON_KEYS)


    def test_to_usd_from_krw(self):
        """
        KRW 비용이 고정 환율 기준으로 USD로 정상 변환되는지 확인한다.
        """

        result = to_usd(1350.0, "KRW")

        self.assertEqual(result, 1.0)


    def test_to_usd_from_usd(self):
        """
        이미 USD인 비용은 같은 값으로 유지되는지 확인한다.
        """

        result = to_usd(1.5, "USD")

        self.assertEqual(result, 1.5)


    def test_to_usd_unsupported_currency(self):
        """
        지원하지 않는 통화가 입력되면
        잘못된 환율을 적용하지 않고 ValueError가 발생하는지 확인한다.
        """

        with self.assertRaises(ValueError):
            to_usd(100.0, "EUR")


    def test_to_common_cost_record(self):
        """
        Azure 비용 원본 데이터가 공통 비용 레코드로
        정상 변환되는지 확인한다.
        """

        row = {
            "Cost": 1350.0,
            "UsageDate": 20260707,
            "ServiceName": "Storage",
            "ResourceId": "test-resource-id",
            "Currency": "KRW",
        }

        record = to_common_cost_record(row)

        self.assertEqual(record["cloud"], "Azure")
        self.assertEqual(record["date"], "2026-07-07")
        self.assertEqual(record["cost_usd"], 1.0)
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["service"], "Storage")
        self.assertEqual(record["granularity"], "DAILY")


if __name__ == "__main__":
    unittest.main()