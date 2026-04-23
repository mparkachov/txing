from __future__ import annotations

import json
import time
import unittest
from dataclasses import dataclass
from typing import Any

from board.mcp_service import BoardMcpServer
from board.cmd_vel import DriveState
from aws.mcp_topics import build_mcp_session_s2c_topic


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


class _FakeCmdVelController:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.stop_reasons: list[str] = []
        self.drive_state = DriveState(0, 0, 0)

    def handle_message(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        self.messages.append(payload)
        self.drive_state = DriveState(40, 40, self.drive_state.sequence + 1)
        return True

    def stop(self, *, reason: str, force: bool = False) -> None:
        del force
        self.stop_reasons.append(reason)
        self.drive_state = DriveState(0, 0, self.drive_state.sequence + 1)

    def get_drive_state(self) -> DriveState:
        return self.drive_state


def _decode_payload(call: _PublishCall) -> dict[str, Any]:
    raw = call.payload
    if isinstance(raw, str):
        return json.loads(raw)
    return json.loads(raw.decode("utf-8"))


def _send_rpc(
    *,
    server: BoardMcpServer,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    server.handle_session_message(
        f"txings/unit-local/mcp/session/{session_id}/c2s",
        json.dumps(payload).encode("utf-8"),
    )


def _latest_s2c_payload(client: _FakeMqttClient, session_id: str) -> dict[str, Any]:
    topic = build_mcp_session_s2c_topic("unit-local", session_id)
    for call in reversed(client.publishes):
        if call.topic == topic:
            return _decode_payload(call)
    raise AssertionError(f"No s2c payload published for session {session_id}")


class BoardMcpServerTests(unittest.TestCase):
    def test_publishes_retained_descriptor_and_status_on_connect(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
        )

        server.on_connected(client=client, publish_timeout_seconds=2.0)

        self.assertGreaterEqual(len(client.publishes), 2)
        self.assertEqual(client.publishes[0].topic, "txings/unit-local/mcp/descriptor")
        self.assertIs(client.publishes[0].retain, True)
        self.assertEqual(client.publishes[1].topic, "txings/unit-local/mcp/status")
        self.assertIs(client.publishes[1].retain, True)
        descriptor = _decode_payload(client.publishes[0])
        self.assertEqual(
            descriptor["transports"],
            [
                {
                    "type": "mqtt-jsonrpc",
                    "priority": 100,
                    "topicRoot": "txings/unit-local/mcp",
                    "sessionTopicPattern": {
                        "clientToServer": "txings/unit-local/mcp/session/{sessionId}/c2s",
                        "serverToClient": "txings/unit-local/mcp/session/{sessionId}/s2c",
                    },
                }
            ],
        )
        self.assertIs(_decode_payload(client.publishes[1])["available"], True)

    def test_descriptor_advertises_webrtc_before_mqtt_when_configured(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            webrtc_channel_name="unit-local-board-video",
            webrtc_region="eu-central-1",
        )

        server.on_connected(client=client, publish_timeout_seconds=2.0)

        descriptor = _decode_payload(client.publishes[0])
        self.assertEqual(descriptor["transports"][0]["type"], "webrtc-datachannel")
        self.assertEqual(descriptor["transports"][0]["priority"], 10)
        self.assertEqual(descriptor["transports"][0]["signaling"], "aws-kvs")
        self.assertEqual(descriptor["transports"][0]["channelName"], "unit-local-board-video")
        self.assertEqual(descriptor["transports"][0]["region"], "eu-central-1")
        self.assertEqual(descriptor["transports"][0]["label"], "txing.mcp.v1")
        self.assertEqual(descriptor["transports"][1]["type"], "mqtt-jsonrpc")
        self.assertEqual(descriptor["transports"][1]["priority"], 100)

    def test_initialize_and_tools_list_flow(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        initialized_response = _latest_s2c_payload(client, session_id)
        self.assertEqual(initialized_response["jsonrpc"], "2.0")
        self.assertEqual(initialized_response["id"], 1)
        self.assertEqual(initialized_response["result"]["serverInfo"]["name"], "mcp")

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools_response = _latest_s2c_payload(client, session_id)
        tools = tools_response["result"]["tools"]
        self.assertIn("control.acquire_lease", [tool["name"] for tool in tools])
        self.assertIn("cmd_vel.publish", [tool["name"] for tool in tools])
        self.assertIn("robot.get_state", [tool["name"] for tool in tools])

    def test_lease_and_motion_tool_flow(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            lease_ttl_ms=5000,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )
        acquire_response = _latest_s2c_payload(client, session_id)
        lease_token = acquire_response["result"]["structuredContent"]["leaseToken"]

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "cmd_vel.publish",
                    "arguments": {
                        "leaseToken": lease_token,
                        "twist": {
                            "linear": {"x": 0.2, "y": 0, "z": 0},
                            "angular": {"x": 0, "y": 0, "z": 0.1},
                        },
                    },
                },
            },
        )
        publish_response = _latest_s2c_payload(client, session_id)
        self.assertIs(publish_response["result"]["structuredContent"]["applied"], True)
        self.assertEqual(
            publish_response["result"]["structuredContent"]["motion"],
            {"leftSpeed": 40, "rightSpeed": 40, "sequence": 1},
        )
        self.assertEqual(len(cmd_vel.messages), 1)

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "cmd_vel.stop",
                    "arguments": {"leaseToken": lease_token},
                },
            },
        )
        stop_response = _latest_s2c_payload(client, session_id)
        self.assertIs(stop_response["result"]["structuredContent"]["stopped"], True)
        self.assertEqual(
            stop_response["result"]["structuredContent"]["motion"],
            {"leftSpeed": 0, "rightSpeed": 0, "sequence": 2},
        )
        self.assertIn("cmd_vel.stop", cmd_vel.stop_reasons[-1])

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "control.release_lease",
                    "arguments": {"leaseToken": lease_token},
                },
            },
        )
        release_response = _latest_s2c_payload(client, session_id)
        self.assertIs(release_response["result"]["structuredContent"]["released"], True)
        self.assertIn("lease released", cmd_vel.stop_reasons[-1])

    def test_lease_expiry_stops_motion(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            lease_ttl_ms=10,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )
        time.sleep(0.03)
        server.poll()

        self.assertTrue(any("expired" in reason for reason in cmd_vel.stop_reasons))

    def test_release_lease_keeps_session_initialized(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            lease_ttl_ms=5000,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )
        first_acquire = _latest_s2c_payload(client, session_id)
        first_lease_token = first_acquire["result"]["structuredContent"]["leaseToken"]

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "control.release_lease",
                    "arguments": {"leaseToken": first_lease_token},
                },
            },
        )
        release_response = _latest_s2c_payload(client, session_id)
        self.assertIs(release_response["result"]["structuredContent"]["released"], True)

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )
        second_acquire = _latest_s2c_payload(client, session_id)
        self.assertIn("result", second_acquire)
        self.assertNotEqual(
            second_acquire["result"]["structuredContent"]["leaseToken"],
            first_lease_token,
        )

    def test_robot_get_state_returns_snapshot_for_initialized_session(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            video_state_provider=lambda: {
                "ready": True,
                "status": "ready",
                "viewerConnected": True,
                "lastError": None,
            },
            lease_ttl_ms=5000,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )
        _send_rpc(
            server=server,
            session_id=session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "robot.get_state", "arguments": {}},
            },
        )
        state_response = _latest_s2c_payload(client, session_id)["result"]["structuredContent"]

        self.assertEqual(
            state_response["control"],
            {
                "leaseRequired": True,
                "leaseTtlMs": 5000,
                "leaseHeldByCaller": True,
                "leaseOwnerSessionId": session_id,
                "leaseExpiresAtMs": state_response["control"]["leaseExpiresAtMs"],
            },
        )
        self.assertEqual(
            state_response["motion"],
            {"leftSpeed": 0, "rightSpeed": 0, "sequence": 0},
        )
        self.assertEqual(
            state_response["video"],
            {
                "available": True,
                "ready": True,
                "status": "ready",
                "viewerConnected": True,
                "lastError": None,
            },
        )

    def test_handle_session_payload_can_send_responses_without_mqtt(self) -> None:
        cmd_vel = _FakeCmdVelController()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
        )
        responses: list[dict[str, Any]] = []

        handled = server.handle_session_payload(
            session_id="webrtc-session-a",
            payload_bytes=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            ).encode("utf-8"),
            response_sender=lambda payload: responses.append(json.loads(payload.decode("utf-8"))),
        )

        self.assertTrue(handled)
        self.assertEqual(responses[0]["jsonrpc"], "2.0")
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "mcp")

    def test_close_session_stops_only_owned_lease(self) -> None:
        cmd_vel = _FakeCmdVelController()
        client = _FakeMqttClient()
        server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            lease_ttl_ms=5000,
        )
        server.on_connected(client=client, publish_timeout_seconds=2.0)
        owner_session_id = "session-a"

        _send_rpc(
            server=server,
            session_id=owner_session_id,
            payload={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=owner_session_id,
            payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        _send_rpc(
            server=server,
            session_id=owner_session_id,
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "control.acquire_lease", "arguments": {}},
            },
        )

        stop_count = len(cmd_vel.stop_reasons)
        server.close_session(session_id="session-b", reason="peer closed")
        self.assertEqual(len(cmd_vel.stop_reasons), stop_count)

        server.close_session(session_id=owner_session_id, reason="peer closed")
        self.assertEqual(len(cmd_vel.stop_reasons), stop_count + 1)
        self.assertIn("peer closed", cmd_vel.stop_reasons[-1])


if __name__ == "__main__":
    unittest.main()
