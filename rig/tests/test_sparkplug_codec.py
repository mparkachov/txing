from __future__ import annotations

import unittest

from rig.sparkplug import DataType, Metric, build_device_report_payload, decode_payload


class SparkplugCodecMetricTypeTests(unittest.TestCase):
    def test_encodes_boolean_and_string_metric_values(self) -> None:
        payload = decode_payload(
            build_device_report_payload(
                redcon=2,
                battery_mv=3777,
                seq=11,
                extra_metrics=(
                    Metric(
                        name="services/mcp/available",
                        datatype=DataType.BOOLEAN,
                        bool_value=True,
                    ),
                    Metric(
                        name="services/mcp/transport",
                        datatype=DataType.STRING,
                        string_value="mqtt-jsonrpc",
                    ),
                ),
            )
        )

        metrics_by_name = {metric.name: metric for metric in payload.metrics}
        self.assertIs(metrics_by_name["services/mcp/available"].bool_value, True)
        self.assertEqual(
            metrics_by_name["services/mcp/transport"].string_value,
            "mqtt-jsonrpc",
        )


if __name__ == "__main__":
    unittest.main()
