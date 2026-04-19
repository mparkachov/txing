from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from board.video_state import (
    DEFAULT_VIDEO_CHANNEL_NAME,
    VIDEO_STATUS_ERROR,
    VIDEO_TRANSPORT,
    build_reported_video_state,
    default_video_state_payload,
    load_video_state,
    normalize_video_state,
)


class VideoStateTests(unittest.TestCase):
    def test_default_state_uses_aws_webrtc_session_shape(self) -> None:
        payload = default_video_state_payload(
            channel_name=DEFAULT_VIDEO_CHANNEL_NAME,
        )

        self.assertEqual(payload["transport"], VIDEO_TRANSPORT)
        self.assertEqual(payload["session"]["channelName"], DEFAULT_VIDEO_CHANNEL_NAME)
        self.assertIs(payload["viewerConnected"], False)

    def test_normalize_state_reads_session_and_error_fields(self) -> None:
        normalized = normalize_video_state(
            {
                "status": "ready",
                "ready": True,
                "transport": "aws-webrtc",
                "session": {
                    "channelName": " txing-board-video ",
                },
                "viewerConnected": True,
                "lastError": " ignored until next publish ",
            }
        )

        self.assertEqual(normalized["status"], "ready")
        self.assertEqual(normalized["session"]["channelName"], "txing-board-video")
        self.assertIs(normalized["viewerConnected"], True)
        self.assertEqual(normalized["lastError"], "ignored until next publish")

    def test_build_reported_state_omits_runtime_timestamp(self) -> None:
        reported = build_reported_video_state(
            {
                "status": "ready",
                "ready": True,
                "transport": "aws-webrtc",
                "session": {"channelName": "txing-board-video"},
                "codec": {
                    "video": "h264",
                },
                "viewerConnected": False,
                "lastError": None,
                "updatedAt": "2026-03-25T12:00:00Z",
            }
        )

        self.assertNotIn("updatedAt", reported)
        self.assertNotIn("session", reported)

    def test_load_video_state_returns_error_for_invalid_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "video-state.json"
            state_file.write_text("{", encoding="utf-8")

            loaded = load_video_state(
                state_file,
                channel_name=DEFAULT_VIDEO_CHANNEL_NAME,
            )

        self.assertEqual(loaded["status"], VIDEO_STATUS_ERROR)
        self.assertIn("invalid video sender state file", loaded["lastError"])

    def test_load_video_state_uses_default_when_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            loaded = load_video_state(
                Path(tmpdir) / "missing.json",
                channel_name=DEFAULT_VIDEO_CHANNEL_NAME,
            )

        self.assertEqual(loaded["session"]["channelName"], DEFAULT_VIDEO_CHANNEL_NAME)

    def test_load_video_state_reads_saved_payload(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "video-state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "ready": True,
                        "transport": "aws-webrtc",
                        "session": {"channelName": "txing-board-video"},
                        "viewerConnected": True,
                        "lastError": None,
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_video_state(state_file)

        self.assertEqual(loaded["status"], "ready")
        self.assertIs(loaded["viewerConnected"], True)


if __name__ == "__main__":
    unittest.main()
