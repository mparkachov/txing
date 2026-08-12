from __future__ import annotations

import unittest

from aws.mavlink_topics import (
    MAVLINK_ACTIVE_LEASE_TTL_MS,
    MAVLINK_DATA_CHANNEL_LABEL,
    MAVLINK_PROTOCOL_VERSION,
    MAVLINK_SERVICE_NAME,
    build_mavlink_descriptor_payload,
    build_mavlink_descriptor_topic,
    build_mavlink_status_payload,
    build_mavlink_status_topic,
    build_mavlink_topic_root,
    build_mavlink_topics,
    parse_mavlink_descriptor_or_status_topic,
    MavlinkActiveControl,
    MavlinkError,
    MavlinkTarget,
)


class MavlinkTopicsContractTests(unittest.TestCase):
    def test_builds_retained_topics(self) -> None:
        topics = build_mavlink_topics("cyberbrick-a1")

        self.assertEqual(topics.topic_root, "txings/cyberbrick-a1/mavlink")
        self.assertEqual(topics.descriptor, "txings/cyberbrick-a1/mavlink/descriptor")
        self.assertEqual(topics.status, "txings/cyberbrick-a1/mavlink/status")
        self.assertEqual(build_mavlink_topic_root("cyberbrick-a1"), topics.topic_root)
        self.assertEqual(build_mavlink_descriptor_topic("cyberbrick-a1"), topics.descriptor)
        self.assertEqual(build_mavlink_status_topic("cyberbrick-a1"), topics.status)

    def test_parses_only_mavlink_descriptor_and_status_topics(self) -> None:
        self.assertEqual(
            parse_mavlink_descriptor_or_status_topic("txings/cyberbrick-a1/mavlink/descriptor"),
            ("cyberbrick-a1", "descriptor"),
        )
        self.assertEqual(
            parse_mavlink_descriptor_or_status_topic("txings/cyberbrick-a1/mavlink/status"),
            ("cyberbrick-a1", "status"),
        )
        self.assertIsNone(
            parse_mavlink_descriptor_or_status_topic("txings/cyberbrick-a1/mcp/status")
        )

    def test_builds_descriptor_with_data_only_contract(self) -> None:
        payload = build_mavlink_descriptor_payload(
            device_id="cyberbrick-a1",
            channel_name="cyberbrick-a1-mavlink",
            region="eu-central-1",
            server_name="txing-cyberbrick-daemon",
            server_version="0.1.0",
        )

        self.assertEqual(payload["serviceId"], MAVLINK_SERVICE_NAME)
        self.assertEqual(payload["protocolVersion"], MAVLINK_PROTOCOL_VERSION)
        self.assertEqual(payload["dataChannel"]["label"], MAVLINK_DATA_CHANNEL_LABEL)
        self.assertIs(payload["dataChannel"]["ordered"], True)
        self.assertIs(payload["dataChannel"]["reliable"], True)
        self.assertEqual(payload["control"]["sessionAuthority"], "daemon")
        self.assertEqual(payload["control"]["leaseTtlMs"], MAVLINK_ACTIVE_LEASE_TTL_MS)
        self.assertNotIn("observedAtMs", payload)
        self.assertNotIn("updatedAtMs", payload)

    def test_builds_status_without_generic_timestamps(self) -> None:
        payload = build_mavlink_status_payload(
            available=True,
            link_state="ready",
            heartbeat_fresh=True,
            target=MavlinkTarget(system_id=1, component_id=1),
            armed=False,
            mode="hold",
            connected_peers=2,
            observer_peers=1,
            active_control=MavlinkActiveControl(
                session_id="peer-a",
                actor="operator@example.test",
                epoch=4,
            ),
            errors=[MavlinkError(code="transport_degraded", message="retrying UDP")],
        )

        self.assertEqual(payload["target"], {"systemId": 1, "componentId": 1})
        self.assertEqual(payload["activeControl"]["leaseTtlMs"], MAVLINK_ACTIVE_LEASE_TTL_MS)
        self.assertEqual(payload["errors"], [{"code": "transport_degraded", "message": "retrying UDP"}])
        self.assertNotIn("observedAtMs", payload)
        self.assertNotIn("updatedAtMs", payload)
        self.assertNotIn("timestamp", payload)

    def test_rejects_invalid_status_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "both be set"):
            MavlinkTarget(system_id=1, component_id=None).as_payload()
        with self.assertRaisesRegex(ValueError, "observer_peers"):
            build_mavlink_status_payload(
                available=False,
                link_state="unavailable",
                heartbeat_fresh=False,
                target=MavlinkTarget(system_id=None, component_id=None),
                armed=False,
                mode=None,
                connected_peers=0,
                observer_peers=1,
                active_control=None,
            )


if __name__ == "__main__":
    unittest.main()
