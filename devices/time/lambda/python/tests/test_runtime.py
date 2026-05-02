from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from time_device.runtime import (
    TIME_MODE_ACTIVE,
    TIME_MODE_SLEEP,
    TIME_DEVICE_SEARCH_QUERY,
    TimeDeviceRuntime,
    build_runtime_from_env,
    build_mcp_session_s2c_topic,
    build_time_command_result_topic,
    build_time_command_topic,
    build_time_state_topic,
    handle_scheduled_wake_for_time_devices,
)


class FakeIotDataClient:
    def __init__(self) -> None:
        self.retained: dict[str, bytes] = {}
        self.published: list[dict[str, object]] = []
        self.shadow_updates: list[dict[str, object]] = []
        self.time_reported: dict[str, object] = {}

    def get_retained_message(self, *, topic: str) -> dict[str, object]:
        return {"payload": self.retained.get(topic, b"")}

    def get_thing_shadow(self, *, thingName: str, shadowName: str) -> dict[str, object]:
        del thingName
        if shadowName != "time":
            return {"payload": b'{"state":{"reported":{}}}'}
        return {
            "payload": json.dumps(
                {
                    "state": {
                        "reported": self.time_reported,
                    }
                }
            ).encode("utf-8")
        }

    def publish(self, **kwargs: object) -> None:
        self.published.append(kwargs)

    def update_thing_shadow(self, **kwargs: object) -> None:
        self.shadow_updates.append(kwargs)
        if kwargs.get("shadowName") == "time":
            payload = decode_payload(kwargs["payload"])
            state = payload["state"]
            assert isinstance(state, dict)
            reported = state["reported"]
            assert isinstance(reported, dict)
            self.time_reported = dict(reported)


class FakeIotClient:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.requests: list[dict[str, object]] = []

    def search_index(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        page = len(self.requests) - 1
        return self.pages[page]


def decode_payload(value: object) -> dict[str, object]:
    assert isinstance(value, bytes)
    decoded = json.loads(value.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def command_payload(
    *,
    command_id: str = "cmd-1",
    power: bool = True,
    deadline_ms: int = 1714380060000,
) -> bytes:
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "commandId": command_id,
            "thingName": "clock",
            "seq": 1,
            "target": {
                "power": power,
            },
            "reason": "redcon=1",
            "issuedAtMs": 1714380000000,
            "deadlineMs": deadline_ms,
        }
    ).encode("utf-8")


class TimeDeviceRuntimeTests(unittest.TestCase):
    def make_runtime(self) -> tuple[TimeDeviceRuntime, FakeIotDataClient]:
        iot = FakeIotDataClient()
        runtime = TimeDeviceRuntime(
            thing_name="clock",
            iot_data_client=iot,
            active_ttl_ms=300_000,
        )
        return runtime, iot

    def test_runtime_from_env_uses_global_version_with_server_override(self) -> None:
        with patch.dict(
            "os.environ",
            {"TXING_VERSION": "0.6.0+g123456789abc"},
            clear=True,
        ):
            runtime = build_runtime_from_env(thing_name="clock", iot_data_client=object())
        self.assertEqual(runtime.server_version, "0.6.0+g123456789abc")

        with patch.dict(
            "os.environ",
            {
                "TXING_VERSION": "0.6.0+g123456789abc",
                "SERVER_VERSION": "0.6.0+gfeedfacefeed",
            },
            clear=True,
        ):
            runtime = build_runtime_from_env(thing_name="clock", iot_data_client=object())
        self.assertEqual(runtime.server_version, "0.6.0+gfeedfacefeed")

    def test_minute_wake_publishes_current_time_and_sleep_state(self) -> None:
        runtime, iot = self.make_runtime()

        with patch("time_device.runtime.utc_now_ms", return_value=1714380000000):
            result = runtime.handle_scheduled_wake({})

        self.assertEqual(result["mode"], TIME_MODE_SLEEP)
        self.assertEqual(iot.time_reported["mode"], TIME_MODE_SLEEP)
        state_publish = next(
            item for item in iot.published if item["topic"] == build_time_state_topic("clock")
        )
        state_payload = decode_payload(state_publish["payload"])
        self.assertEqual(state_payload["currentTimeIso"], "2024-04-29T08:40:00Z")
        self.assertEqual(state_payload["mode"], TIME_MODE_SLEEP)
        self.assertFalse(state_payload["mcpAvailable"])
        self.assertTrue(state_publish["retain"])

    def test_new_redcon_one_command_enters_active_mode_and_publishes_mcp_status(self) -> None:
        runtime, iot = self.make_runtime()
        iot.retained[build_time_command_topic("clock")] = command_payload(command_id="cmd-active")

        with patch("time_device.runtime.utc_now_ms", return_value=1714380000000):
            result = runtime.handle_scheduled_wake({})

        self.assertEqual(result["mode"], TIME_MODE_ACTIVE)
        self.assertEqual(result["activeUntilMs"], 1714380300000)
        self.assertEqual(iot.time_reported["lastCommandId"], "cmd-active")
        command_result_publish = next(
            item
            for item in iot.published
            if item["topic"] == build_time_command_result_topic("clock")
        )
        self.assertEqual(decode_payload(command_result_publish["payload"])["status"], "succeeded")
        status_publish = next(
            item for item in iot.published if item["topic"] == "txings/clock/mcp/status"
        )
        self.assertTrue(decode_payload(status_publish["payload"])["available"])

    def test_mcp_time_now_responds_over_session_topic_while_active(self) -> None:
        runtime, iot = self.make_runtime()
        iot.time_reported = {
            "mode": TIME_MODE_ACTIVE,
            "activeUntilMs": 1714380300000,
            "seq": 1,
        }
        event = {
            "mqttTopic": "txings/clock/mcp/session/session-1/c2s",
            "payloadBase64": base64.b64encode(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {
                            "name": "time.now",
                            "arguments": {},
                        },
                    }
                ).encode("utf-8")
            ).decode("ascii"),
        }

        with patch("time_device.runtime.utc_now_ms", return_value=1714380005000):
            result = runtime.handle_mcp_message(event)

        self.assertTrue(result["active"])
        response_publish = next(
            item
            for item in iot.published
            if item["topic"] == build_mcp_session_s2c_topic("clock", "session-1")
        )
        payload = decode_payload(response_publish["payload"])
        self.assertEqual(payload["id"], 7)
        self.assertEqual(
            payload["result"]["structuredContent"]["currentTimeIso"],
            "2024-04-29T08:40:05Z",
        )
        self.assertFalse(response_publish["retain"])

    def test_expired_retained_command_is_ignored(self) -> None:
        runtime, iot = self.make_runtime()
        iot.retained[build_time_command_topic("clock")] = command_payload(
            command_id="expired",
            deadline_ms=1714379999000,
        )

        with patch("time_device.runtime.utc_now_ms", return_value=1714380000000):
            result = runtime.handle_scheduled_wake({})

        self.assertEqual(result["mode"], TIME_MODE_SLEEP)
        self.assertIsNone(result["lastCommandId"])
        self.assertFalse(
            any(item["topic"] == build_time_command_result_topic("clock") for item in iot.published)
        )
        self.assertIsNone(iot.time_reported.get("lastCommandId"))

    def test_active_mode_times_out_to_redcon_four_state(self) -> None:
        runtime, iot = self.make_runtime()
        iot.time_reported = {
            "mode": TIME_MODE_ACTIVE,
            "activeUntilMs": 1714379999999,
            "lastCommandId": "cmd-active",
            "seq": 3,
        }

        with patch("time_device.runtime.utc_now_ms", return_value=1714380000000):
            result = runtime.handle_scheduled_wake({})

        self.assertEqual(result["mode"], TIME_MODE_SLEEP)
        self.assertIsNone(result["activeUntilMs"])
        state_publish = next(
            item for item in iot.published if item["topic"] == build_time_state_topic("clock")
        )
        self.assertFalse(decode_payload(state_publish["payload"])["mcpAvailable"])

    def test_scheduled_wake_processes_paginated_time_things(self) -> None:
        iot = FakeIotClient(
            [
                {
                    "things": [{"thingName": "clock-a"}],
                    "nextToken": "page-2",
                },
                {
                    "things": [{"thingName": "clock-b"}],
                },
            ]
        )
        iot_data = FakeIotDataClient()

        with patch("time_device.runtime.utc_now_ms", return_value=1714380000000):
            result = handle_scheduled_wake_for_time_devices(
                {},
                iot_client=iot,
                iot_data_client=iot_data,
                active_ttl_ms=300_000,
                server_version="test",
            )

        self.assertEqual(result["thingCount"], 2)
        self.assertEqual(result["processedCount"], 2)
        self.assertEqual(result["failedCount"], 0)
        self.assertEqual(iot.requests[0]["queryString"], TIME_DEVICE_SEARCH_QUERY)
        self.assertEqual(iot.requests[1]["nextToken"], "page-2")
        self.assertTrue(
            any(item["topic"] == build_time_state_topic("clock-a") for item in iot_data.published)
        )
        self.assertTrue(
            any(item["topic"] == build_time_state_topic("clock-b") for item in iot_data.published)
        )

    def test_scheduled_wake_reports_one_device_failure_and_continues(self) -> None:
        iot = FakeIotClient(
            [
                {
                    "things": [{"thingName": "clock-a"}, {"thingName": "clock-b"}],
                }
            ]
        )

        with patch.object(
            TimeDeviceRuntime,
            "handle_scheduled_wake",
            autospec=True,
            side_effect=[RuntimeError("boom"), {"thingName": "clock-b", "mode": TIME_MODE_SLEEP}],
        ):
            with self.assertLogs("time_device.runtime", level="ERROR"):
                result = handle_scheduled_wake_for_time_devices(
                    {},
                    iot_client=iot,
                    iot_data_client=object(),
                    active_ttl_ms=300_000,
                    server_version="test",
                )

        self.assertEqual(result["thingCount"], 2)
        self.assertEqual(result["processedCount"], 1)
        self.assertEqual(result["failedCount"], 1)
        self.assertEqual(result["processed"][0]["thingName"], "clock-b")
        self.assertEqual(result["failed"][0]["thingName"], "clock-a")
        self.assertEqual(result["failed"][0]["errorType"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
