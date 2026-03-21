from __future__ import annotations

import unittest

from board.media_runtime import (
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_PROBE_HOST,
    DEFAULT_STREAM_PATH,
    build_http_url,
    build_live_media_state,
    detect_viewer_host,
    probe_viewer_page,
)


class MediaRuntimeTests(unittest.TestCase):
    def test_http_url_uses_trailing_slash_for_ipv4(self) -> None:
        viewer_url = build_http_url("192.168.1.20", DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertEqual(viewer_url, "http://192.168.1.20:8889/board-cam/")

    def test_http_url_wraps_ipv6_in_brackets(self) -> None:
        viewer_url = build_http_url("2001:db8::20", DEFAULT_MEDIAMTX_VIEWER_PORT, DEFAULT_STREAM_PATH)

        self.assertEqual(viewer_url, "http://[2001:db8::20]:8889/board-cam/")

    def test_detect_viewer_host_prefers_ipv4(self) -> None:
        viewer_host = detect_viewer_host(
            "",
            ipv4="192.168.1.20",
            ipv6="2001:db8::20",
        )

        self.assertEqual(viewer_host, "192.168.1.20")

    def test_detect_viewer_host_falls_back_to_ipv6(self) -> None:
        viewer_host = detect_viewer_host(
            "",
            ipv4=None,
            ipv6="2001:db8::20",
        )

        self.assertEqual(viewer_host, "2001:db8::20")

    def test_probe_returns_error_when_viewer_is_unreachable(self) -> None:
        probe_error = probe_viewer_page(
            host=DEFAULT_PROBE_HOST,
            port=1,
            stream_path=DEFAULT_STREAM_PATH,
            timeout_seconds=0.1,
        )

        self.assertIsInstance(probe_error, str)
        self.assertIn("MediaMTX probe failed", probe_error)

    def test_live_media_state_reports_missing_route_as_error(self) -> None:
        media_state = build_live_media_state(
            stream_path=DEFAULT_STREAM_PATH,
            viewer_port=DEFAULT_MEDIAMTX_VIEWER_PORT,
            viewer_host_override="",
            probe_host=DEFAULT_PROBE_HOST,
            probe_timeout_seconds=0.1,
            route_ipv4=None,
            route_ipv6=None,
        )

        self.assertIs(media_state["ready"], False)
        self.assertEqual(media_state["status"], "error")
        self.assertIsNone(media_state["local"]["viewerUrl"])
        self.assertIn("default-route", media_state["lastError"])


if __name__ == "__main__":
    unittest.main()
