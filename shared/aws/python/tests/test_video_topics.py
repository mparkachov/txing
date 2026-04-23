from __future__ import annotations

import unittest

from aws.video_topics import (
    VIDEO_DEFAULT_CODEC,
    VIDEO_SERVICE_NAME,
    VIDEO_STATUS_READY,
    VIDEO_STATUS_UNAVAILABLE,
    VIDEO_TRANSPORT,
    build_video_descriptor_payload,
    build_video_descriptor_topic,
    build_video_status_payload,
    build_video_status_topic,
    build_video_topic_root,
    build_video_topics,
    parse_video_descriptor_or_status_topic,
)


class VideoTopicsContractTests(unittest.TestCase):
    def test_builds_device_first_topics(self) -> None:
        topics = build_video_topics("unit-local")
        self.assertEqual(topics.topic_root, "txings/unit-local/video")
        self.assertEqual(topics.descriptor, "txings/unit-local/video/descriptor")
        self.assertEqual(topics.status, "txings/unit-local/video/status")

    def test_builds_descriptor_and_status_topics(self) -> None:
        self.assertEqual(build_video_topic_root("unit-local"), "txings/unit-local/video")
        self.assertEqual(
            build_video_descriptor_topic("unit-local"),
            "txings/unit-local/video/descriptor",
        )
        self.assertEqual(
            build_video_status_topic("unit-local"),
            "txings/unit-local/video/status",
        )

    def test_parses_descriptor_and_status_topics(self) -> None:
        self.assertEqual(
            parse_video_descriptor_or_status_topic("txings/unit-local/video/descriptor"),
            ("unit-local", "descriptor"),
        )
        self.assertEqual(
            parse_video_descriptor_or_status_topic("txings/unit-local/video/status"),
            ("unit-local", "status"),
        )
        self.assertIsNone(
            parse_video_descriptor_or_status_topic("txings/unit-local/video/session/a")
        )

    def test_builds_descriptor_payload(self) -> None:
        payload = build_video_descriptor_payload(
            device_id="unit-local",
            channel_name="unit-local-board-video",
            region="eu-central-1",
            server_version="0.3.0",
        )

        self.assertEqual(payload["serviceId"], VIDEO_SERVICE_NAME)
        self.assertEqual(payload["transport"], VIDEO_TRANSPORT)
        self.assertEqual(payload["topicRoot"], "txings/unit-local/video")
        self.assertEqual(payload["descriptorTopic"], "txings/unit-local/video/descriptor")
        self.assertEqual(payload["statusTopic"], "txings/unit-local/video/status")
        self.assertEqual(payload["channelName"], "unit-local-board-video")
        self.assertEqual(payload["region"], "eu-central-1")
        self.assertEqual(payload["codec"], {"video": VIDEO_DEFAULT_CODEC})

    def test_builds_status_payload(self) -> None:
        payload = build_video_status_payload(
            available=True,
            ready=True,
            status=VIDEO_STATUS_READY,
            viewer_connected=True,
            last_error=None,
            updated_at_ms=67890,
        )

        self.assertEqual(payload["serviceId"], VIDEO_SERVICE_NAME)
        self.assertIs(payload["available"], True)
        self.assertIs(payload["ready"], True)
        self.assertEqual(payload["status"], VIDEO_STATUS_READY)
        self.assertIs(payload["viewerConnected"], True)
        self.assertIsNone(payload["lastError"])
        self.assertEqual(payload["updatedAtMs"], 67890)

    def test_allows_unavailable_status_payload(self) -> None:
        payload = build_video_status_payload(
            available=False,
            ready=False,
            status=VIDEO_STATUS_UNAVAILABLE,
        )

        self.assertIs(payload["available"], False)
        self.assertEqual(payload["status"], VIDEO_STATUS_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
