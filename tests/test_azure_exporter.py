import unittest

from collectors.azure_exporter import to_common_record


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


if __name__ == "__main__":
    unittest.main()