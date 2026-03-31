from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rig.ble_bridge import (
    BleSleepBridge,
    BridgeConfig,
    ShadowState,
    _build_shadow_from_snapshot,
    _calculate_redcon,
    _parse_args,
    _shadow_payload_includes_desired_redcon,
)
from rig.sparkplug import (
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


class ServiceConfigTests(unittest.TestCase):
    def test_parse_args_accepts_service_environment_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "THING_NAME": "txing-prod",
                "RIG_THING_NAME": "rig-prod",
                "TOWN_THING_NAME": "town-prod",
                "SPARKPLUG_GROUP_ID": "town-prod",
                "SPARKPLUG_EDGE_NODE_ID": "rig-prod",
                "IOT_ENDPOINT_FILE": "/tmp/iot-endpoint",
                "CERT_FILE": "/tmp/cert.pem",
                "KEY_FILE": "/tmp/key.pem",
                "CA_FILE": "/tmp/ca.pem",
                "CLOUDWATCH_LOG_GROUP": "/town/rig/txing-prod",
            },
            clear=True,
        ):
            with patch("sys.argv", ["rig"]):
                args = _parse_args()

        self.assertEqual(args.thing_name, "txing-prod")
        self.assertEqual(args.rig_thing_name, "rig-prod")
        self.assertEqual(args.town_thing_name, "town-prod")
        self.assertEqual(args.sparkplug_group_id, "town-prod")
        self.assertEqual(args.sparkplug_edge_node_id, "rig-prod")
        self.assertEqual(args.iot_endpoint_file, Path("/tmp/iot-endpoint"))
        self.assertEqual(args.cert_file, Path("/tmp/cert.pem"))
        self.assertEqual(args.key_file, Path("/tmp/key.pem"))
        self.assertEqual(args.ca_file, Path("/tmp/ca.pem"))
        self.assertEqual(args.cloudwatch_log_group, "/town/rig/txing-prod")

    def test_justfile_install_service_exports_environment(self) -> None:
        justfile = (Path(__file__).resolve().parents[2] / "rig" / "justfile").read_text(
            encoding="utf-8"
        )

        self.assertIn('Environment="AWS_REGION={{region}}"', justfile)
        self.assertIn('Environment="THING_NAME={{thing_name}}"', justfile)
        self.assertIn('Environment="RIG_THING_NAME={{rig_thing_name}}"', justfile)
        self.assertIn('Environment="TOWN_THING_NAME={{town_thing_name}}"', justfile)
        self.assertIn('Environment="SPARKPLUG_GROUP_ID={{sparkplug_group_id}}"', justfile)
        self.assertIn(
            'Environment="SPARKPLUG_EDGE_NODE_ID={{sparkplug_edge_node_id}}"',
            justfile,
        )
        self.assertIn('Environment="IOT_ENDPOINT_FILE={{endpoint_file}}"', justfile)
        self.assertIn('Environment="CERT_FILE={{cert_file}}"', justfile)
        self.assertIn('Environment="KEY_FILE={{key_file}}"', justfile)
        self.assertIn('Environment="CA_FILE={{ca_file}}"', justfile)
        self.assertIn('Environment="CLOUDWATCH_LOG_GROUP={{cloudwatch_log_group}}"', justfile)
        self.assertIn('ExecStart={{built_rig}}', justfile)


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
                            "batteryMv": 3795,
                            "mcu": {
                                "power": True,
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
                                "batteryMv": 3795,
                                "mcu": {
                                    "power": False,
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
                            "batteryMv": 3795,
                            "mcu": {
                                "power": False,
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
