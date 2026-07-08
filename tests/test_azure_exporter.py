import unittest

from collectors.azure_exporter import (
    to_common_cost_record,
    to_common_record,
    to_usd,
)


class TestAzureExporter(unittest.TestCase):

    def test_to_common_record_full_fields(self):
        """
        모든 필드가 공통 레코드에 정상적으로 전달되는지 확인한다.
        """

        raw = {
            "cloud": "azure",
            "resource_id": "vm-finops-azure-test",
            "resource_type": "vm",
            "region": "koreacentral",
            "metric_name": "Percentage CPU",
            "timestamp": "2026-07-07T10:19:00Z",
            "cpu_percent": 0.525,
            "memory_percent": 48.29,
            "disk_percent": 10.7,
            "instance_type": "Standard_B2ats_v2",
            "vcpu": 2,
            "ram_gb": 1.0,
            "cost_monthly": None,
            "source": "actual",
        }

        record = to_common_record(raw)

        self.assertEqual(record["cloud"], "azure")
        self.assertEqual(record["resource_id"], "vm-finops-azure-test")
        self.assertEqual(record["resource_type"], "vm")
        self.assertEqual(record["region"], "koreacentral")

        self.assertEqual(record["cpu_percent"], 0.525)
        self.assertEqual(record["memory_percent"], 48.29)
        self.assertEqual(record["disk_percent"], 10.7)

        self.assertEqual(record["instance_type"], "Standard_B2ats_v2")
        self.assertEqual(record["vcpu"], 2)
        self.assertEqual(record["ram_gb"], 1.0)

        self.assertIsNone(record["cost_monthly"])
        self.assertEqual(record["source"], "actual")


    def test_to_common_record_handles_none_metrics(self):
        """
        메모리와 디스크 값이 없어도 None 상태로 정상 변환되는지 확인한다.
        """

        raw = {
            "cloud": "azure",
            "resource_id": "vm-test",
            "resource_type": "vm",
            "region": "koreacentral",
            "metric_name": "Percentage CPU",
            "timestamp": "2026-07-07T10:19:00Z",
            "cpu_percent": 20.0,
            "memory_percent": None,
            "disk_percent": None,
            "instance_type": "Standard_B1s",
            "vcpu": 1,
            "ram_gb": 1.0,
            "cost_monthly": None,
            "source": "actual",
        }

        record = to_common_record(raw)

        self.assertEqual(record["cloud"], "azure")
        self.assertIsNone(record["memory_percent"])
        self.assertIsNone(record["disk_percent"])
        self.assertIsNone(record["cost_monthly"])


    def test_to_common_record_preserves_zero_values(self):
        """
        사용률이 0.0인 경우 None으로 바뀌지 않고
        실제 숫자 0.0으로 유지되는지 확인한다.
        """

        raw = {
            "cloud": "azure",
            "resource_id": "vm-test",
            "resource_type": "vm",
            "region": "koreacentral",
            "metric_name": "Percentage CPU",
            "timestamp": "2026-07-07T10:19:00Z",
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
            "instance_type": "Standard_B1s",
            "vcpu": 1,
            "ram_gb": 1.0,
            "cost_monthly": None,
            "source": "actual",
        }

        record = to_common_record(raw)

        self.assertEqual(record["cpu_percent"], 0.0)
        self.assertEqual(record["memory_percent"], 0.0)
        self.assertEqual(record["disk_percent"], 0.0)


    def test_internal_metric_name_is_removed(self):
        """
        Azure 내부 처리용 metric_name이
        공통 레코드에는 포함되지 않는지 확인한다.
        """

        raw = {
            "cloud": "azure",
            "resource_id": "vm-test",
            "resource_type": "vm",
            "region": "koreacentral",
            "metric_name": "Percentage CPU",
            "timestamp": "2026-07-07T10:19:00Z",
            "cpu_percent": 10.0,
            "memory_percent": 40.0,
            "disk_percent": 20.0,
            "instance_type": "Standard_B1s",
            "vcpu": 1,
            "ram_gb": 1.0,
            "cost_monthly": None,
            "source": "actual",
        }

        record = to_common_record(raw)

        self.assertNotIn("metric_name", record)


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

        self.assertEqual(record["cloud"], "azure")
        self.assertEqual(record["date"], "2026-07-07")
        self.assertEqual(record["cost_usd"], 1.0)
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["service"], "Storage")
        self.assertEqual(record["granularity"], "DAILY")


if __name__ == "__main__":
    unittest.main()