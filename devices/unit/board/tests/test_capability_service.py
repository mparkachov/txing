from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from board.capability_service import (
    BOARD_CAPABILITY_ADAPTER_ID,
    BoardCapabilityService,
    build_capability_state_topic,
)


@dataclass(slots=True)
class _PublishCall:
    topic: str
    payload: bytes | str
    retain: bool
    timeout_seconds: float | None


class _FakeMqttClient:
    def __init__(self) -> None:
        self.publishes: list[_PublishCall] = []

    def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        retain: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        self.publishes.append(
            _PublishCall(
                topic=topic,
                payload=payload,
                retain=retain,
                timeout_seconds=timeout_seconds,
            )
        )


def _decode_payload(call: _PublishCall) -> dict[str, Any]:
    raw = call.payload
    if isinstance(raw, str):
        return json.loads(raw)
    return json.loads(raw.decode("utf-8"))


class BoardCapabilityServiceTests(unittest.TestCase):
    def test_builds_retained_capability_state_topic(self) -> None:
        self.assertEqual(
            build_capability_state_topic("unit-local"),
            "txings/unit-local/capability/v2/state",
        )

    def test_publishes_retained_board_mcp_video_state(self) -> None:
        client = _FakeMqttClient()
        service = BoardCapabilityService(
            device_id="unit-local",
            declared_capabilities=("sparkplug", "ble", "power", "board", "mcp", "video"),
            ttl_seconds=150.0,
        )

        with patch("board.capability_service.time.time", return_value=1778706385.734):
            service.on_connected(client=client, publish_timeout_seconds=2.0)
            service.publish_state(
                board_available=True,
                mcp_available=True,
                video_available=True,
            )

        self.assertEqual(len(client.publishes), 1)
        self.assertEqual(client.publishes[0].topic, "txings/unit-local/capability/v2/state")
        self.assertIs(client.publishes[0].retain, True)
        self.assertEqual(client.publishes[0].timeout_seconds, 2.0)
        payload = _decode_payload(client.publishes[0])
        self.assertEqual(payload["schemaVersion"], "2.0")
        self.assertEqual(payload["adapterId"], BOARD_CAPABILITY_ADAPTER_ID)
        self.assertEqual(payload["thingName"], "unit-local")
        self.assertEqual(
            payload["capabilities"],
            {
                "board": True,
                "mcp": True,
                "video": True,
            },
        )
        self.assertEqual(
            payload["expiredCapabilities"],
            {
                "board": False,
                "mcp": False,
                "video": False,
            },
        )
        self.assertEqual(payload["observedAtMs"], 1778706385734)
        self.assertEqual(payload["expiresAtMs"], 1778706535734)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(payload["metrics"], {})

    def test_filters_capabilities_to_declared_board_owned_set(self) -> None:
        client = _FakeMqttClient()
        service = BoardCapabilityService(
            device_id="unit-local",
            declared_capabilities=("sparkplug", "board"),
        )

        service.on_connected(client=client, publish_timeout_seconds=2.0)
        service.publish_state(
            board_available=True,
            mcp_available=True,
            video_available=True,
        )

        payload = _decode_payload(client.publishes[0])
        self.assertEqual(payload["capabilities"], {"board": True})

    def test_republishes_last_state_on_reconnect_with_fresh_expiry(self) -> None:
        first_client = _FakeMqttClient()
        second_client = _FakeMqttClient()
        service = BoardCapabilityService(
            device_id="unit-local",
            declared_capabilities=("board", "mcp", "video"),
            ttl_seconds=10.0,
        )

        with patch("board.capability_service.time.time", return_value=100.0):
            service.on_connected(client=first_client, publish_timeout_seconds=2.0)
            service.publish_state(
                board_available=True,
                mcp_available=True,
                video_available=False,
            )
        service.on_disconnected(reason="simulated")
        with patch("board.capability_service.time.time", return_value=120.0):
            service.on_connected(client=second_client, publish_timeout_seconds=3.0)

        payload = _decode_payload(second_client.publishes[0])
        self.assertEqual(payload["capabilities"]["video"], False)
        self.assertEqual(payload["observedAtMs"], 120000)
        self.assertEqual(payload["expiresAtMs"], 130000)
        self.assertEqual(payload["seq"], 2)
        self.assertEqual(second_client.publishes[0].timeout_seconds, 3.0)

    def test_close_publishes_unavailable_state(self) -> None:
        client = _FakeMqttClient()
        service = BoardCapabilityService(
            device_id="unit-local",
            declared_capabilities=("board", "mcp", "video"),
        )
        service.on_connected(client=client, publish_timeout_seconds=2.0)
        service.publish_state(
            board_available=True,
            mcp_available=True,
            video_available=True,
        )

        service.close()

        payload = _decode_payload(client.publishes[-1])
        self.assertEqual(
            payload["capabilities"],
            {
                "board": False,
                "mcp": False,
                "video": False,
            },
        )
