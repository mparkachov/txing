from __future__ import annotations

import unittest

from aws.mcp_topics import (
    MCP_PROTOCOL_VERSION,
    MCP_TRANSPORT,
    MCP_WEBRTC_DATA_CHANNEL_LABEL,
    MCP_WEBRTC_DATA_CHANNEL_TRANSPORT,
    MCP_WEBRTC_SIGNALING,
    build_mcp_descriptor_payload,
    build_mcp_descriptor_topic,
    build_mcp_session_c2s_subscription,
    build_mcp_session_c2s_topic,
    build_mcp_session_s2c_topic,
    build_mcp_status_payload,
    build_mcp_status_topic,
    build_mcp_topic_root,
    build_mcp_topics,
    parse_mcp_descriptor_or_status_topic,
    parse_mcp_session_c2s_topic,
)


class McpTopicsContractTests(unittest.TestCase):
    def test_builds_device_first_topics(self) -> None:
        topics = build_mcp_topics("unit-local")
        self.assertEqual(topics.topic_root, "txings/unit-local/mcp")
        self.assertEqual(topics.descriptor, "txings/unit-local/mcp/descriptor")
        self.assertEqual(topics.status, "txings/unit-local/mcp/status")
        self.assertEqual(topics.session_c2s_pattern, "txings/unit-local/mcp/session/{sessionId}/c2s")
        self.assertEqual(topics.session_s2c_pattern, "txings/unit-local/mcp/session/{sessionId}/s2c")
        self.assertEqual(topics.session_c2s_subscription, "txings/unit-local/mcp/session/+/c2s")

    def test_builds_descriptor_status_and_session_topics(self) -> None:
        self.assertEqual(build_mcp_topic_root("unit-local"), "txings/unit-local/mcp")
        self.assertEqual(build_mcp_descriptor_topic("unit-local"), "txings/unit-local/mcp/descriptor")
        self.assertEqual(build_mcp_status_topic("unit-local"), "txings/unit-local/mcp/status")
        self.assertEqual(
            build_mcp_session_c2s_topic("unit-local", "session-a"),
            "txings/unit-local/mcp/session/session-a/c2s",
        )
        self.assertEqual(
            build_mcp_session_s2c_topic("unit-local", "session-a"),
            "txings/unit-local/mcp/session/session-a/s2c",
        )
        self.assertEqual(
            build_mcp_session_c2s_subscription("unit-local"),
            "txings/unit-local/mcp/session/+/c2s",
        )

    def test_parses_descriptor_and_status_topics(self) -> None:
        self.assertEqual(
            parse_mcp_descriptor_or_status_topic("txings/unit-local/mcp/descriptor"),
            ("unit-local", "descriptor"),
        )
        self.assertEqual(
            parse_mcp_descriptor_or_status_topic("txings/unit-local/mcp/status"),
            ("unit-local", "status"),
        )
        self.assertIsNone(parse_mcp_descriptor_or_status_topic("txings/unit-local/mcp/session/a/c2s"))

    def test_parses_session_topic_for_target_device(self) -> None:
        self.assertEqual(
            parse_mcp_session_c2s_topic(
                "txings/unit-local/mcp/session/session-a/c2s",
                device_id="unit-local",
            ),
            "session-a",
        )
        self.assertIsNone(
            parse_mcp_session_c2s_topic(
                "txings/other/mcp/session/session-a/c2s",
                device_id="unit-local",
            )
        )

    def test_builds_descriptor_payload(self) -> None:
        payload = build_mcp_descriptor_payload(
            device_id="unit-local",
            server_version="0.2.0",
            lease_ttl_ms=5000,
        )
        self.assertEqual(payload["serviceId"], "mcp")
        self.assertEqual(payload["transport"], MCP_TRANSPORT)
        self.assertEqual(payload["mcpProtocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(payload["topicRoot"], "txings/unit-local/mcp")
        self.assertEqual(payload["descriptorTopic"], "txings/unit-local/mcp/descriptor")
        self.assertEqual(
            payload["sessionTopicPattern"],
            {
                "clientToServer": "txings/unit-local/mcp/session/{sessionId}/c2s",
                "serverToClient": "txings/unit-local/mcp/session/{sessionId}/s2c",
            },
        )
        self.assertEqual(
            payload["transports"],
            [
                {
                    "type": MCP_TRANSPORT,
                    "priority": 100,
                    "topicRoot": "txings/unit-local/mcp",
                    "sessionTopicPattern": {
                        "clientToServer": "txings/unit-local/mcp/session/{sessionId}/c2s",
                        "serverToClient": "txings/unit-local/mcp/session/{sessionId}/s2c",
                    },
                }
            ],
        )
        self.assertEqual(payload["leaseTtlMs"], 5000)

    def test_builds_descriptor_payload_with_webrtc_transport_before_mqtt(self) -> None:
        payload = build_mcp_descriptor_payload(
            device_id="unit-local",
            server_version="0.2.0",
            lease_ttl_ms=5000,
            webrtc_channel_name="unit-local-board-video",
            webrtc_region="eu-central-1",
        )

        self.assertEqual(payload["transport"], MCP_TRANSPORT)
        self.assertEqual(
            payload["transports"],
            [
                {
                    "type": MCP_WEBRTC_DATA_CHANNEL_TRANSPORT,
                    "priority": 10,
                    "signaling": MCP_WEBRTC_SIGNALING,
                    "channelName": "unit-local-board-video",
                    "region": "eu-central-1",
                    "label": MCP_WEBRTC_DATA_CHANNEL_LABEL,
                },
                {
                    "type": MCP_TRANSPORT,
                    "priority": 100,
                    "topicRoot": "txings/unit-local/mcp",
                    "sessionTopicPattern": {
                        "clientToServer": "txings/unit-local/mcp/session/{sessionId}/c2s",
                        "serverToClient": "txings/unit-local/mcp/session/{sessionId}/s2c",
                    },
                },
            ],
        )

    def test_builds_status_payload(self) -> None:
        payload = build_mcp_status_payload(
            available=True,
            lease_owner_session_id="session-a",
            lease_expires_at_ms=12345,
            updated_at_ms=67890,
        )
        self.assertEqual(payload["serviceId"], "mcp")
        self.assertIs(payload["available"], True)
        self.assertEqual(payload["leaseOwnerSessionId"], "session-a")
        self.assertEqual(payload["leaseExpiresAtMs"], 12345)
        self.assertEqual(payload["updatedAtMs"], 67890)


if __name__ == "__main__":
    unittest.main()
