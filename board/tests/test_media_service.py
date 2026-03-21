from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from board.media_service import (
    DEFAULT_MEDIAMTX_RTSP_PORT,
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_RTSP_PUBLISH_HOST,
    DEFAULT_SOURCE_PIPELINE,
    DEFAULT_STREAM_PATH,
    _build_viewer_url,
    _build_gstreamer_command,
)


class MediaServiceTests(unittest.TestCase):
    def test_default_pipeline_is_locked_to_1080p30_hardware_h264(self) -> None:
        args = argparse.Namespace(
            source_pipeline=DEFAULT_SOURCE_PIPELINE,
            stream_path=DEFAULT_STREAM_PATH,
            rtsp_publish_host=DEFAULT_RTSP_PUBLISH_HOST,
            rtsp_publish_port=DEFAULT_MEDIAMTX_RTSP_PORT,
        )

        command = _build_gstreamer_command(args, "gst-launch-1.0")
        command_text = " ".join(command)

        self.assertIn("libcamerasrc", command_text)
        self.assertIn("width=1920", command_text)
        self.assertIn("height=1080", command_text)
        self.assertIn("framerate=30/1", command_text)
        self.assertIn("v4l2h264enc", command_text)
        self.assertIn("rtph264pay", command_text)
        self.assertIn("rtspclientsink", command_text)
        self.assertIn(
            f"location=rtsp://{DEFAULT_RTSP_PUBLISH_HOST}:{DEFAULT_MEDIAMTX_RTSP_PORT}/{DEFAULT_STREAM_PATH}",
            command_text,
        )

    def test_viewer_url_uses_global_ipv6_address(self) -> None:
        mock_addresses = type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": "2001:db8::20"})()

        with patch("board.media_service._detect_default_route_addresses", return_value=mock_addresses):
            viewer_url = _build_viewer_url(DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertEqual(viewer_url, "http://[2001:db8::20]:8889/board-cam")

    def test_viewer_url_is_none_without_ipv6(self) -> None:
        mock_addresses = type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": None})()

        with patch("board.media_service._detect_default_route_addresses", return_value=mock_addresses):
            viewer_url = _build_viewer_url(DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertIsNone(viewer_url)


if __name__ == "__main__":
    unittest.main()
