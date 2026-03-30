from __future__ import annotations

import unittest

from gw.shadow_store import (
    default_shadow_payload,
    get_reported_board_video_ready,
    get_reported_board_video_viewer_connected,
)


class ShadowStoreTests(unittest.TestCase):
    def test_default_shadow_payload_tracks_board_video_defaults(self) -> None:
        payload = default_shadow_payload()

        self.assertFalse(get_reported_board_video_ready(payload))
        self.assertFalse(get_reported_board_video_viewer_connected(payload))


if __name__ == "__main__":
    unittest.main()
