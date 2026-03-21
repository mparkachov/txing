from __future__ import annotations

import unittest
from unittest.mock import patch

from board.media_service import (
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_PROBE_HOST,
    DEFAULT_STREAM_PATH,
    _build_http_url,
    _detect_viewer_host,
    _probe_viewer_page,
)


class MediaServiceTests(unittest.TestCase):
    def test_http_url_uses_trailing_slash_for_ipv4(self) -> None:
        viewer_url = _build_http_url("192.168.1.20", DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertEqual(viewer_url, "http://192.168.1.20:8889/board-cam/")

    def test_http_url_wraps_ipv6_in_brackets(self) -> None:
        viewer_url = _build_http_url("2001:db8::20", DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertEqual(viewer_url, "http://[2001:db8::20]:8889/board-cam/")

    def test_detect_viewer_host_prefers_ipv4(self) -> None:
        mock_addresses = type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": "2001:db8::20"})()

        with patch("board.media_service._detect_default_route_addresses", return_value=mock_addresses):
            viewer_host = _detect_viewer_host("")

        self.assertEqual(viewer_host, "192.168.1.20")

    def test_detect_viewer_host_falls_back_to_ipv6(self) -> None:
        mock_addresses = type("Addresses", (), {"ipv4": None, "ipv6": "2001:db8::20"})()

        with patch("board.media_service._detect_default_route_addresses", return_value=mock_addresses):
            viewer_host = _detect_viewer_host("")

        self.assertEqual(viewer_host, "2001:db8::20")

    def test_probe_returns_error_when_viewer_is_unreachable(self) -> None:
        probe_error = _probe_viewer_page(
            host=DEFAULT_PROBE_HOST,
            port=1,
            stream_path=DEFAULT_STREAM_PATH,
            timeout_seconds=0.1,
        )

        self.assertIsInstance(probe_error, str)
        self.assertIn("MediaMTX probe failed", probe_error)


if __name__ == "__main__":
    unittest.main()
