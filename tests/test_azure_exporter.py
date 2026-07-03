import unittest

from collectors.azure_exporter import to_common_record


class TestAzureExporter(unittest.TestCase):
    def test_to_common_record(self):
        raw = {
            "cloud": "azure",
            "resource_id": "vm-finops-azure-test",
            "resource_type": "vm",
            "region": "koreacentral",
            "metric_name": "Percentage CPU",
            "timestamp": "2026-07-03T12:39:00Z",
            "cpu_percent": 0.24,
            "memory_percent": None,
            "disk_percent": None,
            "source": "actual",
        }

        record = to_common_record(raw)

        self.assertEqual(record["cloud"], "azure")
        self.assertEqual(record["resource_id"], "vm-finops-azure-test")
        self.assertEqual(record["resource_type"], "vm")
        self.assertEqual(record["region"], "koreacentral")
        self.assertEqual(record["timestamp"], "2026-07-03T12:39:00Z")
        self.assertEqual(record["cpu_percent"], 0.24)
        self.assertIsNone(record["memory_percent"])
        self.assertIsNone(record["disk_percent"])
        self.assertEqual(record["source"], "actual")
        self.assertNotIn("metric_name", record)


if __name__ == "__main__":
    unittest.main()