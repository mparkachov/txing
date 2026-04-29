from __future__ import annotations

import unittest

from rig.shadow_store import (
    default_shadow_payload,
    get_reported_battery_mv,
    get_reported_board_power,
    get_reported_board_wifi_online,
    get_reported_redcon,
)


class ShadowStoreTests(unittest.TestCase):
    def test_default_shadow_payload_contains_only_shadow_fields_still_in_contract(self) -> None:
        payload = default_shadow_payload()

        self.assertEqual(get_reported_redcon(payload), 4)
        self.assertEqual(
            payload["state"]["reported"]["device"]["mcu"],
            {
                "power": False,
                "online": False,
                "bleDeviceId": None,
            },
        )
        self.assertEqual(get_reported_battery_mv(payload), 3750)
        self.assertFalse(get_reported_board_power(payload))
        self.assertFalse(get_reported_board_wifi_online(payload))
        self.assertNotIn("video", payload["state"]["reported"]["device"]["board"])

    def test_reported_battery_mv_reads_nested_device_metric_reflection(self) -> None:
        payload = {
            "state": {
                "reported": {
                    "device": {
                        "batteryMv": 3999,
                    },
                },
            },
        }

        self.assertEqual(get_reported_battery_mv(payload), 3999)

    def test_ble_device_id_lives_under_mcu_state(self) -> None:
        payload = {
            "state": {
                "reported": {
                    "device": {
                        "mcu": {
                            "bleDeviceId": "AA:BB:CC:DD:EE:FF",
                        },
                    },
                },
            },
        }

        self.assertIn("bleDeviceId", default_shadow_payload()["state"]["reported"]["device"]["mcu"])
        self.assertIn("bleDeviceId", payload["state"]["reported"]["device"]["mcu"])


if __name__ == "__main__":
    unittest.main()
