from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from board import video_sender


class VideoSenderTests(unittest.TestCase):
    def test_parse_args_uses_rust_sender_marker_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "sys.argv",
                [
                    "board-video-sender",
                    "--region",
                    "eu-central-1",
                    "--viewer-url",
                    "https://ops.example.com/video",
                ],
            ):
                args = video_sender._parse_args()

        self.assertEqual(args.ready_pattern, video_sender.DEFAULT_READY_PATTERN)
        self.assertEqual(
            args.viewer_connected_pattern,
            video_sender.DEFAULT_VIEWER_CONNECTED_PATTERN,
        )
        self.assertEqual(
            args.viewer_disconnected_pattern,
            video_sender.DEFAULT_VIEWER_DISCONNECTED_PATTERN,
        )

    def test_build_sender_environment_exports_region_and_channel_name(self) -> None:
        with patch.dict(os.environ, {"EXISTING": "value"}, clear=True):
            environment = video_sender._build_sender_environment(
                region="eu-central-1",
                channel_name="txing-board-video",
            )

        self.assertEqual(environment["EXISTING"], "value")
        self.assertEqual(environment["TXING_BOARD_VIDEO_REGION"], "eu-central-1")
        self.assertEqual(
            environment["TXING_BOARD_VIDEO_CHANNEL_NAME"],
            "txing-board-video",
        )


if __name__ == "__main__":
    unittest.main()
