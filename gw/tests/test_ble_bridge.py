from __future__ import annotations

import asyncio
import unittest

from gw.ble_bridge import (
    BleSleepBridge,
    BridgeConfig,
    ShadowState,
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
            _calculate_redcon(mcu_power=False, board_power=False, board_wifi_online=False),
            4,
        )
        self.assertEqual(
            _calculate_redcon(mcu_power=True, board_power=False, board_wifi_online=False),
            3,
        )
        self.assertEqual(
            _calculate_redcon(mcu_power=True, board_power=True, board_wifi_online=False),
            2,
        )
        self.assertEqual(
            _calculate_redcon(mcu_power=True, board_power=True, board_wifi_online=True),
            1,
        )


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
