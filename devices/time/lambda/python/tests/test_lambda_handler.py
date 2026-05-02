from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from time_device.lambda_handler import lambda_handler


class TimeDeviceLambdaHandlerTests(unittest.TestCase):
    def test_mcp_invocation_targets_thing_from_topic_without_thing_name_env(self) -> None:
        runtime = Mock()
        runtime.handle_mcp_message.return_value = {
            "thingName": "clock-a",
            "sessionId": "session-1",
            "active": True,
            "responded": True,
        }
        event = {
            "mqttTopic": "txings/clock-a/mcp/session/session-1/c2s",
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        }

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "time_device.lambda_handler.build_runtime_from_env",
                return_value=runtime,
            ) as build_runtime:
                result = lambda_handler(event, object())

        build_runtime.assert_called_once_with(thing_name="clock-a")
        runtime.handle_mcp_message.assert_called_once_with(event)
        self.assertEqual(result["thingName"], "clock-a")

    def test_scheduled_invocation_uses_generic_time_device_scheduler(self) -> None:
        event = {"source": "aws.events"}
        expected = {
            "eventType": "schedule",
            "thingCount": 2,
            "processedCount": 2,
            "failedCount": 0,
            "processed": [],
            "failed": [],
        }

        with patch(
            "time_device.lambda_handler.handle_scheduled_wake_for_time_devices_from_env",
            return_value=expected,
        ) as scheduler:
            result = lambda_handler(event, object())

        scheduler.assert_called_once_with(event)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
