from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from board.video_service import BoardVideoService


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


class BoardVideoServiceTests(unittest.TestCase):
    def test_publishes_retained_descriptor_on_connect(self) -> None:
        client = _FakeMqttClient()
        service = BoardVideoService(
            device_id="unit-local",
            channel_name="unit-local-board-video",
            region="eu-central-1",
        )

        service.on_connected(client=client, publish_timeout_seconds=2.0)

        self.assertEqual(len(client.publishes), 1)
        self.assertEqual(client.publishes[0].topic, "txings/unit-local/video/descriptor")
        self.assertIs(client.publishes[0].retain, True)
        payload = _decode_payload(client.publishes[0])
        self.assertEqual(payload["serviceId"], "video")
        self.assertEqual(payload["serverVersion"], "0.6.0")
        self.assertEqual(payload["channelName"], "unit-local-board-video")
        self.assertEqual(payload["statusTopic"], "txings/unit-local/video/status")

    def test_descriptor_uses_global_txing_version_from_environment(self) -> None:
        client = _FakeMqttClient()
        with patch.dict("os.environ", {"TXING_VERSION": "0.6.0+g123456789abc"}):
            service = BoardVideoService(
                device_id="unit-local",
                channel_name="unit-local-board-video",
                region="eu-central-1",
            )

        service.on_connected(client=client, publish_timeout_seconds=2.0)

        payload = _decode_payload(client.publishes[0])
        self.assertEqual(payload["serverVersion"], "0.6.0+g123456789abc")

    def test_publishes_retained_status_from_local_video_state(self) -> None:
        client = _FakeMqttClient()
        service = BoardVideoService(
            device_id="unit-local",
            channel_name="unit-local-board-video",
            region="eu-central-1",
        )
        service.on_connected(client=client, publish_timeout_seconds=2.0)

        service.publish_status(
            {
                "status": "ready",
                "ready": True,
                "viewerConnected": True,
                "lastError": None,
            }
        )

        self.assertEqual(client.publishes[-1].topic, "txings/unit-local/video/status")
        self.assertIs(client.publishes[-1].retain, True)
        payload = _decode_payload(client.publishes[-1])
        self.assertIs(payload["available"], True)
        self.assertIs(payload["ready"], True)
        self.assertEqual(payload["status"], "ready")
        self.assertIs(payload["viewerConnected"], True)
        self.assertIn("updatedAtMs", payload)

    def test_close_publishes_retained_unavailable_status(self) -> None:
        client = _FakeMqttClient()
        service = BoardVideoService(
            device_id="unit-local",
            channel_name="unit-local-board-video",
            region="eu-central-1",
        )
        service.on_connected(client=client, publish_timeout_seconds=2.0)

        service.close()

        self.assertEqual(client.publishes[-1].topic, "txings/unit-local/video/status")
        payload = _decode_payload(client.publishes[-1])
        self.assertIs(payload["available"], False)
        self.assertIs(payload["ready"], False)
        self.assertEqual(payload["status"], "unavailable")

    def test_republishes_last_retained_status_on_reconnect(self) -> None:
        first_client = _FakeMqttClient()
        second_client = _FakeMqttClient()
        service = BoardVideoService(
            device_id="unit-local",
            channel_name="unit-local-board-video",
            region="eu-central-1",
        )

        service.on_connected(client=first_client, publish_timeout_seconds=2.0)
        service.publish_status(
            {
                "status": "ready",
                "ready": True,
                "viewerConnected": False,
                "lastError": None,
            }
        )
        service.on_disconnected(reason="simulated disconnect")
        service.on_connected(client=second_client, publish_timeout_seconds=2.0)

        self.assertEqual(
            [publish.topic for publish in second_client.publishes],
            [
                "txings/unit-local/video/descriptor",
                "txings/unit-local/video/status",
            ],
        )
        payload = _decode_payload(second_client.publishes[-1])
        self.assertIs(payload["available"], True)
        self.assertIs(payload["ready"], True)
        self.assertEqual(payload["status"], "ready")


if __name__ == "__main__":
    unittest.main()
