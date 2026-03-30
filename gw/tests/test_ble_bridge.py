from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gw.ble_bridge import (
    BleSleepBridge,
    BridgeConfig,
    ShadowState,
    _build_shadow_from_snapshot,
    _calculate_redcon,
    _shadow_payload_includes_desired_power,
)


class ShadowPayloadTests(unittest.TestCase):
    def test_update_payload_without_desired_power_does_not_claim_desired(self) -> None:
        payload = {"state": {"reported": {"mcu": {"power": True}}}}
        self.assertFalse(_shadow_payload_includes_desired_power(payload))

    def test_update_payload_with_null_desired_power_still_claims_desired(self) -> None:
        payload = {"state": {"desired": {"mcu": {"power": None}}}}
        self.assertTrue(_shadow_payload_includes_desired_power(payload))


class RedconTests(unittest.TestCase):
    def test_calculates_redcon_from_reported_posture(self) -> None:
        self.assertEqual(
            _calculate_redcon(
                mcu_power=False,
                board_power=False,
                board_wifi_online=False,
                board_video_ready=False,
                board_video_viewer_connected=False,
            ),
            4,
        )
        self.assertEqual(
            _calculate_redcon(
                mcu_power=True,
                board_power=False,
                board_wifi_online=False,
                board_video_ready=False,
                board_video_viewer_connected=False,
            ),
            3,
        )
        self.assertEqual(
            _calculate_redcon(
                mcu_power=True,
                board_power=True,
                board_wifi_online=True,
                board_video_ready=False,
                board_video_viewer_connected=False,
            ),
            3,
        )
        self.assertEqual(
            _calculate_redcon(
                mcu_power=True,
                board_power=True,
                board_wifi_online=True,
                board_video_ready=True,
                board_video_viewer_connected=False,
            ),
            2,
        )
        self.assertEqual(
            _calculate_redcon(
                mcu_power=True,
                board_power=True,
                board_wifi_online=True,
                board_video_ready=True,
                board_video_viewer_connected=True,
            ),
            1,
        )

    def test_builds_shadow_state_from_board_video_snapshot(self) -> None:
        with TemporaryDirectory() as tmpdir:
            shadow = _build_shadow_from_snapshot(
                {
                    "state": {
                        "reported": {
                            "redcon": 1,
                            "mcu": {
                                "power": True,
                                "batteryMv": 3795,
                                "ble": {
                                    "serviceUuid": "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "sleepCommandUuid": "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "stateReportUuid": "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "online": True,
                                },
                            },
                            "board": {
                                "power": True,
                                "wifi": {
                                    "online": True,
                                },
                                "video": {
                                    "ready": True,
                                    "viewerConnected": True,
                                },
                            },
                        },
                    },
                },
                snapshot_file=Path(tmpdir) / "shadow.json",
            )

        self.assertTrue(shadow.board_video_ready)
        self.assertTrue(shadow.board_video_viewer_connected)
        self.assertEqual(shadow.redcon, 1)


class WaitForReportedPowerTests(unittest.TestCase):
    def test_wait_for_reported_power_accepts_shadow_state_after_read_failure(self) -> None:
        asyncio.run(self._exercise_wait_for_reported_power_read_failure())

    async def _exercise_wait_for_reported_power_read_failure(self) -> None:
        shadow = ShadowState(desired_power=True, reported_power=False, battery_mv=3729)
        bridge = BleSleepBridge(
            BridgeConfig(command_ack_timeout=0.2, command_ack_poll_interval=0.01),
            shadow,
            cloud_shadow=object(),  # type: ignore[arg-type]
        )

        class FakeClient:
            is_connected = True

        async def fail_after_shadow_sync() -> bytes:
            shadow.set_reported(True, battery_mv=3729)
            bridge._last_state_report = bytes((0x00, 0x91, 0x0E))
            raise RuntimeError("simulated gatt read failure")

        bridge._client = FakeClient()  # type: ignore[assignment]
        bridge._read_state_report = fail_after_shadow_sync  # type: ignore[method-assign]

        report = await bridge._wait_for_reported_power(True)

        self.assertEqual(report, bytes((0x00, 0x91, 0x0E)))


if __name__ == "__main__":
    unittest.main()
