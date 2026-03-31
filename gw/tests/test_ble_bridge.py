from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gw.ble_bridge import (
    BleSleepBridge,
    BridgeConfig,
    ShadowState,
    _build_shadow_from_snapshot,
    _calculate_redcon,
    _shadow_payload_includes_desired_redcon,
)
from gw.sparkplug import (
    build_device_topic,
    build_device_report_payload,
    build_redcon_payload,
    build_node_redcon_payload,
    build_node_topic,
    decode_payload,
    decode_redcon_command,
)


class FakeCloudShadow:
    def __init__(self) -> None:
        self.shadow_updates: list[dict[str, object]] = []
        self.sparkplug_publishes: list[tuple[str, bytes]] = []

    async def update_shadow(self, **kwargs: object) -> None:
        self.shadow_updates.append(kwargs)

    async def publish_sparkplug(self, topic: str, payload: bytes, **_: object) -> None:
        self.sparkplug_publishes.append((topic, payload))


class ShadowPayloadTests(unittest.TestCase):
    def test_update_payload_without_desired_redcon_does_not_claim_desired(self) -> None:
        payload = {"state": {"reported": {"mcu": {"power": True}}}}
        self.assertFalse(_shadow_payload_includes_desired_redcon(payload))

    def test_update_payload_with_null_desired_redcon_still_claims_desired(self) -> None:
        payload = {"state": {"desired": {"redcon": None}}}
        self.assertTrue(_shadow_payload_includes_desired_redcon(payload))


class RedconTests(unittest.TestCase):
    def test_calculates_redcon_from_reported_posture(self) -> None:
        self.assertEqual(
            _calculate_redcon(
                ble_online=True,
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
                ble_online=True,
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
                ble_online=True,
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
                ble_online=True,
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
                ble_online=True,
                mcu_power=True,
                board_power=True,
                board_wifi_online=True,
                board_video_ready=True,
                board_video_viewer_connected=True,
            ),
            1,
        )
        self.assertEqual(
            _calculate_redcon(
                ble_online=False,
                mcu_power=True,
                board_power=True,
                board_wifi_online=True,
                board_video_ready=True,
                board_video_viewer_connected=True,
            ),
            4,
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

    def test_desired_redcon_only_converges_after_target_is_reached(self) -> None:
        shadow = ShadowState(desired_redcon=2, redcon=3)

        self.assertFalse(shadow.clear_desired_redcon_if_converged())

        shadow.redcon = 2
        self.assertTrue(shadow.clear_desired_redcon_if_converged())

        shadow.desired_redcon = 4
        shadow.redcon = 3
        self.assertFalse(shadow.clear_desired_redcon_if_converged())

        shadow.redcon = 4
        self.assertTrue(shadow.clear_desired_redcon_if_converged())


class WaitForReportedPowerTests(unittest.TestCase):
    def test_wait_for_reported_power_accepts_shadow_state_after_read_failure(self) -> None:
        asyncio.run(self._exercise_wait_for_reported_power_read_failure())

    async def _exercise_wait_for_reported_power_read_failure(self) -> None:
        shadow = ShadowState(desired_redcon=3, reported_power=False, battery_mv=3729)
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


class LifecycleBridgeTests(unittest.TestCase):
    def test_redcon_four_requests_internal_board_shutdown_before_sleep(self) -> None:
        asyncio.run(self._exercise_redcon_four_board_shutdown_request())

    async def _exercise_redcon_four_board_shutdown_request(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            desired_redcon=4,
            reported_power=True,
            battery_mv=3795,
            ble_online=True,
            board_power=True,
            redcon=3,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )

        await bridge._process_desired_redcon_once()

        self.assertEqual(shadow.desired_redcon, 4)
        self.assertIs(shadow.desired_board_power, False)
        self.assertEqual(len(cloud_shadow.shadow_updates), 1)
        self.assertIs(cloud_shadow.shadow_updates[0]["desired_board_power"], False)

    def test_ddeath_clears_desired_state_and_publishes_device_death(self) -> None:
        asyncio.run(self._exercise_ddeath_clears_desired_state())

    async def _exercise_ddeath_clears_desired_state(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            desired_redcon=3,
            desired_board_power=False,
            reported_power=True,
            battery_mv=3812,
            ble_online=True,
            redcon=3,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._publish_ble_online_state(
            online=False,
            context="unit-test ddeath",
            force=True,
        )

        self.assertFalse(shadow.ble_online)
        self.assertEqual(shadow.redcon, 4)
        self.assertIsNone(shadow.desired_redcon)
        self.assertIsNone(shadow.desired_board_power)
        self.assertFalse(bridge._sparkplug_device_born)
        self.assertEqual(len(cloud_shadow.sparkplug_publishes), 1)
        self.assertEqual(
            cloud_shadow.sparkplug_publishes[0][0],
            "spBv1.0/town/DDEATH/rig/txing",
        )
        ddeath = decode_payload(cloud_shadow.sparkplug_publishes[0][1])
        self.assertEqual(ddeath.seq, 0)
        self.assertEqual(ddeath.metrics[0].name, "redcon")
        self.assertEqual(ddeath.metrics[0].int_value, 4)
        self.assertEqual(len(cloud_shadow.shadow_updates), 2)
        self.assertIsNone(cloud_shadow.shadow_updates[1]["desired_redcon"])
        self.assertIsNone(cloud_shadow.shadow_updates[1]["desired_board_power"])


class SnapshotRecoveryTests(unittest.TestCase):
    def test_restart_recovers_cached_desired_redcon_when_snapshot_omits_it(self) -> None:
        with TemporaryDirectory() as tmpdir:
            snapshot_file = Path(tmpdir) / "shadow.json"
            snapshot_file.write_text(
                json.dumps(
                    {
                        "state": {
                            "desired": {
                                "redcon": 3,
                                "board": {
                                    "power": None,
                                },
                            },
                            "reported": {
                                "redcon": 4,
                                "mcu": {
                                    "power": False,
                                    "batteryMv": 3795,
                                    "ble": {
                                        "serviceUuid": "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100",
                                        "sleepCommandUuid": "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100",
                                        "stateReportUuid": "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100",
                                        "online": False,
                                    },
                                },
                                "board": {
                                    "power": False,
                                    "wifi": {
                                        "online": False,
                                    },
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            shadow = _build_shadow_from_snapshot(
                {
                    "state": {
                        "reported": {
                            "redcon": 4,
                            "mcu": {
                                "power": False,
                                "batteryMv": 3795,
                                "ble": {
                                    "serviceUuid": "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "sleepCommandUuid": "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "stateReportUuid": "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100",
                                    "online": False,
                                },
                            },
                        }
                    }
                },
                snapshot_file=snapshot_file,
            )

        self.assertEqual(shadow.desired_redcon, 3)
        self.assertIsNone(shadow.desired_board_power)


class SparkplugCodecTests(unittest.TestCase):
    def test_decodes_redcon_command_payload(self) -> None:
        command = decode_redcon_command(build_redcon_payload(redcon=3, seq=5))

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.metric_name, "redcon")
        self.assertEqual(command.value, 3)
        self.assertEqual(command.seq, 5)

    def test_encodes_node_redcon_payload(self) -> None:
        topic = build_node_topic("town", "NBIRTH", "rig")
        payload = decode_payload(build_node_redcon_payload(redcon=1, seq=9))

        self.assertEqual(topic, "spBv1.0/town/NBIRTH/rig")
        self.assertEqual(payload.seq, 9)
        self.assertEqual(payload.metrics[0].name, "rig.redcon")
        self.assertEqual(payload.metrics[0].int_value, 1)

    def test_builds_phase_one_device_topics_and_payload_sequences(self) -> None:
        self.assertEqual(
            build_device_topic("town", "DCMD", "rig", "txing"),
            "spBv1.0/town/DCMD/rig/txing",
        )
        self.assertEqual(
            build_device_topic("town", "DBIRTH", "rig", "txing"),
            "spBv1.0/town/DBIRTH/rig/txing",
        )
        self.assertEqual(
            build_device_topic("town", "DDATA", "rig", "txing"),
            "spBv1.0/town/DDATA/rig/txing",
        )
        self.assertEqual(
            build_device_topic("town", "DDEATH", "rig", "txing"),
            "spBv1.0/town/DDEATH/rig/txing",
        )

        payload = decode_payload(build_device_report_payload(redcon=2, battery_mv=3777, seq=11))

        self.assertEqual(payload.seq, 11)
        self.assertEqual(len(payload.metrics), 2)
        self.assertEqual(payload.metrics[0].name, "redcon")
        self.assertEqual(payload.metrics[0].int_value, 2)
        self.assertEqual(payload.metrics[1].name, "batteryMv")
        self.assertEqual(payload.metrics[1].int_value, 3777)


if __name__ == "__main__":
    unittest.main()
