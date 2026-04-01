from __future__ import annotations

import unittest

from rig.shadow_store import (
    default_shadow_payload,
    get_desired_board_power,
    get_desired_redcon,
    get_reported_battery_mv,
    get_reported_board_video_ready,
    get_reported_board_video_viewer_connected,
)


class ShadowStoreTests(unittest.TestCase):
    def test_default_shadow_payload_tracks_board_video_defaults(self) -> None:
        payload = default_shadow_payload()

        self.assertIsNone(get_desired_redcon(payload))
        self.assertIsNone(get_desired_board_power(payload))
        self.assertEqual(get_reported_battery_mv(payload), 3750)
        self.assertFalse(get_reported_board_video_ready(payload))
        self.assertFalse(get_reported_board_video_viewer_connected(payload))

    def test_reported_battery_mv_only_reads_top_level_metric_reflection(self) -> None:
        payload = {
            "state": {
                "reported": {
                    "mcu": {
                        "batteryMv": 3999,
                    },
                },
            },
        }

        self.assertEqual(get_reported_battery_mv(payload), 3750)

    def test_default_shadow_payload_does_not_expose_registry_metadata(self) -> None:
        payload = {
            "state": {
                "reported": {
                    "bleDeviceId": "AA:BB:CC:DD:EE:FF",
                    "homeRig": "rig-a",
                },
            },
        }

        self.assertNotIn("bleDeviceId", default_shadow_payload()["state"]["reported"])
        self.assertIn("bleDeviceId", payload["state"]["reported"])


if __name__ == "__main__":
    unittest.main()
