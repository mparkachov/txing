from __future__ import annotations

from argparse import Namespace
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from board.cmd_vel import DriveState
from board.shadow_control import (
    AwsShadowClient,
    DEFAULT_AWS_CONNECT_TIMEOUT,
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_MCP_LEASE_TTL_MS,
    DEFAULT_MQTT_PUBLISH_TIMEOUT,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_TIME_SYNC_TIMEOUT,
    DEFAULT_VIDEO_REGION,
    DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS,
    ControlConfig,
    DefaultRouteAddresses,
    REPO_ROOT,
    _build_board_report,
    _build_cmd_vel_controller,
    _build_cmd_vel_motor_driver,
    _build_shutdown_board_report,
    _build_shadow_update,
    _decode_sparkplug_redcon_command,
    _discover_repo_root,
    _load_validator,
    _validate_shadow_update,
    _wait_for_system_clock_sync,
)
from board.video_state import DEFAULT_VIDEO_CHANNEL_NAME, build_reported_video_state
import board.shadow_control as shadow_control

UNIT_AWS_DIR = REPO_ROOT / "devices" / "unit" / "aws"
UNIT_BOARD_DIR = REPO_ROOT / "devices" / "unit" / "board"


def _make_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "shadow_file": Path("/tmp/unit_board_shadow.json"),
        "thing_name": "unit-local",
        "schema_file": Path(UNIT_AWS_DIR / "board-shadow.schema.json"),
        "client_id": None,
        "video_region": DEFAULT_VIDEO_REGION,
        "video_sender_command": "/tmp/bot-board-kvs-master",
        "aws_shared_credentials_file": Path("/tmp/credentials"),
        "aws_config_file": Path("/tmp/config"),
        "video_startup_timeout_seconds": DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS,
        "board_name": "bot-board-test",
        "heartbeat_seconds": DEFAULT_HEARTBEAT_SECONDS,
        "aws_connect_timeout": DEFAULT_AWS_CONNECT_TIMEOUT,
        "publish_timeout": DEFAULT_MQTT_PUBLISH_TIMEOUT,
        "reconnect_delay": DEFAULT_RECONNECT_DELAY,
        "time_sync_timeout_seconds": DEFAULT_TIME_SYNC_TIMEOUT,
        "drive_raw_max_speed": 480,
        "drive_cmd_raw_min_speed": 0,
        "drive_cmd_raw_max_speed": 480,
        "drive_pwm_hz": 20_000,
        "drive_pwm_chip": 0,
        "drive_left_pwm_channel": 0,
        "drive_right_pwm_channel": 1,
        "drive_gpio_chip": 0,
        "drive_left_dir_gpio": 5,
        "drive_right_dir_gpio": 6,
        "drive_left_inverted": False,
        "drive_right_inverted": False,
        "halt_command": ["/bin/true"],
        "mcp_webrtc_socket_file": None,
        "disable_mcp_webrtc": False,
        "once": False,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _make_video_state(
    *,
    ready: bool,
    viewer_connected: bool = False,
    last_error: str | None = None,
) -> dict[str, object]:
    return {
        "status": "ready" if ready else "error",
        "ready": ready,
        "transport": "aws-webrtc",
        "session": {"channelName": "unit-local-board-video"},
        "codec": {
            "video": "h264",
        },
        "viewerConnected": viewer_connected,
        "lastError": last_error,
    }


def _make_config(**overrides: object) -> ControlConfig:
    values: dict[str, object] = {
        "thing_name": "unit-local",
        "aws_region": "eu-central-1",
        "iot_endpoint": "example-ats.iot.eu-central-1.amazonaws.com",
        "sparkplug_group_id": "town",
        "sparkplug_edge_node_id": "rig",
        "capabilities_set": ("sparkplug", "device", "mcu", "board", "video"),
        "schema_file": Path(UNIT_AWS_DIR / "board-shadow.schema.json"),
        "video_schema_file": Path(UNIT_AWS_DIR / "video-shadow.schema.json"),
        "shadow_file": Path("/tmp/unit_board_shadow.json"),
        "client_id": "bot-board-test",
        "video_channel_name": DEFAULT_VIDEO_CHANNEL_NAME,
        "video_region": DEFAULT_VIDEO_REGION,
        "video_sender_command": "/tmp/bot-board-kvs-master",
        "aws_shared_credentials_file": Path("/tmp/credentials"),
        "aws_config_file": Path("/tmp/config"),
        "video_startup_timeout_seconds": DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS,
        "board_name": "bot-board-test",
        "heartbeat_seconds": DEFAULT_HEARTBEAT_SECONDS,
        "aws_connect_timeout": DEFAULT_AWS_CONNECT_TIMEOUT,
        "publish_timeout": DEFAULT_MQTT_PUBLISH_TIMEOUT,
        "reconnect_delay": DEFAULT_RECONNECT_DELAY,
        "time_sync_timeout_seconds": DEFAULT_TIME_SYNC_TIMEOUT,
        "drive_raw_max_speed": 480,
        "drive_cmd_raw_min_speed": 0,
        "drive_cmd_raw_max_speed": 480,
        "drive_pwm_hz": 20_000,
        "drive_pwm_chip": 0,
        "drive_left_pwm_channel": 0,
        "drive_right_pwm_channel": 1,
        "drive_gpio_chip": 0,
        "drive_left_dir_gpio": 5,
        "drive_right_dir_gpio": 6,
        "drive_left_inverted": False,
        "drive_right_inverted": False,
        "halt_command": ("/bin/true",),
        "mcp_webrtc_socket_file": None,
        "once": False,
    }
    values.update(overrides)
    return ControlConfig(**values)


def _make_runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.iot_data_endpoint.return_value = "example-ats.iot.eu-central-1.amazonaws.com"
    runtime.iot_client.return_value.describe_thing.return_value = {
        "thingName": "unit-local",
        "thingTypeName": "unit",
        "attributes": {
            "townId": "town-local",
            "rigId": "rig-local",
            "deviceType": "unit",
            "name": "bot",
            "shortId": "local00",
            "capabilities": "sparkplug,mcu,board,mcp,video",
        },
    }
    return runtime


class ShadowControlContractTests(unittest.TestCase):
    def test_aws_shadow_connect_initializes_mcp_before_requesting_shadow_snapshot(self) -> None:
        events: list[str] = []

        class _FakeConnection:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.subscriptions: list[str] = []

            def connect(self, *, timeout_seconds: float) -> None:
                del timeout_seconds
                events.append("connect")

            def disconnect(self, *, timeout_seconds: float) -> None:
                del timeout_seconds

            def subscribe(
                self,
                topic: str,
                _handler: object,
                *,
                timeout_seconds: float,
            ) -> None:
                del timeout_seconds
                self.subscriptions.append(topic)

            def publish(
                self,
                topic: str,
                payload: str,
                *,
                timeout_seconds: float,
            ) -> None:
                del payload, timeout_seconds
                events.append(f"publish:{topic}")

        mcp_server = MagicMock()
        mcp_server.session_c2s_subscription = "txings/unit-local/mcp/session/+/c2s"
        mcp_server.status_topic = "txings/unit-local/mcp/status"
        mcp_server.build_unavailable_status_payload.return_value = b'{"available":false}'
        mcp_server.on_connected.side_effect = lambda **_kwargs: events.append("mcp-connected")

        with patch.object(shadow_control, "AwsIotWebsocketSyncConnection", _FakeConnection):
            shadow_client = AwsShadowClient(
                _make_config(),
                aws_runtime=_make_runtime(),
                mcp_server=mcp_server,
            )
            shadow_client.ensure_connected(timeout_seconds=1.0)

        self.assertEqual(events[0:2], ["connect", "mcp-connected"])
        self.assertEqual(events[2], "publish:$aws/things/unit-local/shadow/name/board/get")
        mcp_server.on_connected.assert_called_once()

    def test_aws_shadow_connect_waits_for_failed_client_close_before_retry(self) -> None:
        events: list[str] = []
        first_client_closed = threading.Event()
        test_case = self

        class _FakeConnection:
            _next_instance_id = 0

            def __init__(self, *_args: object, **kwargs: object) -> None:
                type(self)._next_instance_id += 1
                self.instance_id = type(self)._next_instance_id
                self._on_connection_closed = kwargs["on_connection_closed"]

            def connect(self, *, timeout_seconds: float) -> None:
                del timeout_seconds
                events.append(f"connect:{self.instance_id}")

            def disconnect(self, *, timeout_seconds: float) -> None:
                del timeout_seconds
                events.append(f"disconnect:{self.instance_id}")

                def _close() -> None:
                    if self.instance_id == 1:
                        first_client_closed.set()
                    self._on_connection_closed({"instance": self.instance_id})

                threading.Timer(0.05, _close).start()

            def subscribe(
                self,
                topic: str,
                _handler: object,
                *,
                timeout_seconds: float,
            ) -> None:
                del timeout_seconds
                events.append(f"subscribe:{self.instance_id}:{topic}")
                if self.instance_id == 1:
                    raise RuntimeError(
                        (
                            "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION: "
                            "Old requests from the previous session are cancelled"
                        )
                    )
                test_case.assertTrue(
                    first_client_closed.is_set(),
                    "retry started before previous clean-session client closed",
                )

            def publish(
                self,
                topic: str,
                payload: str,
                *,
                timeout_seconds: float,
            ) -> None:
                del payload, timeout_seconds
                events.append(f"publish:{topic}")

        with patch.object(shadow_control, "AwsIotWebsocketSyncConnection", _FakeConnection):
            shadow_client = AwsShadowClient(
                _make_config(),
                aws_runtime=_make_runtime(),
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "failed to subscribe to shadow update topics",
            ):
                shadow_client.ensure_connected(timeout_seconds=1.0)
            self.assertTrue(
                first_client_closed.is_set(),
                "failed startup should wait for on_connection_closed before retrying",
            )
            shadow_client.ensure_connected(timeout_seconds=1.0)

        self.assertEqual(
            events[0:3],
            [
                "connect:1",
                "subscribe:1:$aws/things/unit-local/shadow/name/board/get/accepted",
                "disconnect:1",
            ],
        )
        self.assertIn("connect:2", events)
        self.assertIn("publish:$aws/things/unit-local/shadow/name/board/get", events)

    def test_decodes_sparkplug_redcon_command_metric(self) -> None:
        payload = bytes(
            [
                0x12,
                0x0C,
                0x0A,
                0x06,
                0x72,
                0x65,
                0x64,
                0x63,
                0x6F,
                0x6E,
                0x20,
                0x03,
                0x50,
                0x03,
            ]
        )

        self.assertEqual(_decode_sparkplug_redcon_command(payload), 3)

    def test_board_shadow_update_is_reported_only(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "board-shadow.schema.json"))
        payload = _build_shadow_update(_build_shutdown_board_report())

        _validate_shadow_update(validator, payload)
        self.assertNotIn("desired", payload["state"])
        self.assertIs(payload["state"]["reported"]["power"], False)
        self.assertIs(payload["state"]["reported"]["wifi"]["online"], False)

    def test_board_report_without_video_matches_schema(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "board-shadow.schema.json"))
        report = _build_board_report(
            addresses=type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": "2001:db8::20"})(),
            power=True,
        )

        _validate_shadow_update(validator, {"state": {"reported": report}})
        self.assertNotIn("video", report)
        self.assertNotIn("drive", report)

    def test_default_shadow_reset_payload_matches_schema(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "board-shadow.schema.json"))
        payload = json.loads(
            Path(UNIT_AWS_DIR / "default-board-shadow.json").read_text(encoding="utf-8")
        )

        _validate_shadow_update(validator, payload)
        self.assertIs(payload["state"]["reported"]["power"], False)
        self.assertIs(payload["state"]["reported"]["wifi"]["online"], False)

    def test_default_video_shadow_reset_payload_matches_schema(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "video-shadow.schema.json"))
        payload = json.loads(
            Path(UNIT_AWS_DIR / "default-video-shadow.json").read_text(encoding="utf-8")
        )

        _validate_shadow_update(validator, payload)
        self.assertIs(payload["state"]["reported"]["status"]["available"], False)
        self.assertEqual(payload["state"]["reported"]["status"]["status"], "unavailable")

    def test_reported_video_state_omits_runtime_timestamp(self) -> None:
        reported = build_reported_video_state(
            {
                "status": "ready",
                "ready": True,
                "transport": "aws-webrtc",
                "session": {"channelName": "unit-local-board-video"},
                "codec": {
                    "video": "h264",
                },
                "viewerConnected": False,
                "lastError": None,
                "updatedAt": "2026-03-25T12:00:00Z",
            }
        )

        self.assertNotIn("updatedAt", reported)

    def test_cmd_vel_controller_watchdog_aligns_with_mcp_lease_window(self) -> None:
        motor_driver = MagicMock()
        controller = _build_cmd_vel_controller(
            _make_config(),
            motor_driver=motor_driver,
            lease_ttl_ms=DEFAULT_MCP_LEASE_TTL_MS,
        )
        try:
            self.assertEqual(
                controller._watchdog_timeout_seconds,  # noqa: SLF001
                DEFAULT_MCP_LEASE_TTL_MS / 1000.0,
            )
        finally:
            controller.close()

    def test_wait_for_system_clock_sync_returns_when_clock_becomes_synchronized(self) -> None:
        stop_event = threading.Event()

        with (
            patch.object(
                shadow_control,
                "_query_system_clock_synchronized",
                side_effect=[False, True],
            ),
            patch.object(shadow_control, "DEFAULT_TIME_SYNC_POLL_INTERVAL", 0.0),
        ):
            _wait_for_system_clock_sync(stop_event, 1.0)

    def test_wait_for_system_clock_sync_proceeds_when_timedatectl_unavailable(self) -> None:
        stop_event = threading.Event()

        with patch.object(
            shadow_control,
            "_query_system_clock_synchronized",
            return_value=None,
        ):
            _wait_for_system_clock_sync(stop_event, 1.0)

    def test_main_once_publishes_shadow_without_waiting_for_video_ready(self) -> None:
        args = _make_args(once=True)
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.read_state.return_value = _make_video_state(
            ready=False,
            last_error="sender warming up",
        )
        video_service = MagicMock()

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=_make_runtime()),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(shadow_control, "_wait_for_system_clock_sync"),
            patch.object(shadow_control, "_build_cmd_vel_motor_driver", return_value=MagicMock()),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(shadow_control, "BoardVideoService", return_value=video_service),
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor) as video_supervisor_cls,
        ):
            shadow_control.main()

        self.assertEqual(
            video_supervisor_cls.call_args.kwargs["working_directory"],
            shadow_control.REPO_ROOT,
        )
        self.assertEqual(video_supervisor.read_state.call_count, 1)
        self.assertEqual(shadow_client.publish_update.call_count, 2)
        self.assertEqual(
            shadow_client.publish_update.call_args_list[0].kwargs["shadow_name"],
            "video",
        )
        payload = shadow_client.publish_update.call_args_list[1].args[0]
        self.assertNotIn("video", payload["state"]["reported"])
        self.assertNotIn("drive", payload["state"]["reported"])
        video_service.publish_status.assert_called_once()

    def test_main_republishes_video_status_and_video_shadow_after_runtime_error(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.return_code.return_value = None
        video_supervisor.read_state.side_effect = [
            _make_video_state(ready=True),
            _make_video_state(ready=False, last_error="video sender exited"),
            _make_video_state(ready=False, last_error="video sender exited"),
            _make_video_state(ready=False, last_error="video sender exited"),
        ]
        video_service = MagicMock()

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=_make_runtime()),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(shadow_control, "_wait_for_system_clock_sync"),
            patch.object(shadow_control, "_build_cmd_vel_motor_driver", return_value=MagicMock()),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(shadow_control, "_wait_for_stop_or_halt", side_effect=[False, True]),
            patch.object(shadow_control, "BoardVideoService", return_value=video_service),
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 3)
        self.assertEqual(
            shadow_client.publish_update.call_args_list[0].kwargs["shadow_name"],
            "video",
        )
        self.assertEqual(
            shadow_client.publish_update.call_args_list[2].kwargs["shadow_name"],
            "video",
        )
        payload = shadow_client.publish_update.call_args_list[1].args[0]
        self.assertNotIn("video", payload["state"]["reported"])
        self.assertEqual(video_service.publish_status.call_count, 2)
        self.assertIs(video_service.publish_status.call_args_list[0].args[0]["ready"], True)
        self.assertIs(video_service.publish_status.call_args_list[1].args[0]["ready"], False)
        self.assertEqual(
            video_service.publish_status.call_args_list[1].args[0]["lastError"],
            "video sender exited",
        )

    def test_main_honors_halt_requested_without_video_startup_gate(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.side_effect = [False, False, True, True]
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.read_state.return_value = _make_video_state(
            ready=False,
            last_error="video sender boot failed",
        )
        video_service = MagicMock()

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=_make_runtime()),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(shadow_control, "_wait_for_system_clock_sync"),
            patch.object(shadow_control, "_build_cmd_vel_motor_driver", return_value=MagicMock()),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(shadow_control, "_request_system_halt") as request_system_halt,
            patch.object(shadow_control, "BoardVideoService", return_value=video_service),
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 3)
        payload = shadow_client.publish_update.call_args_list[-1].args[0]
        self.assertIs(payload["state"]["reported"]["power"], False)
        self.assertNotIn("desired", payload["state"])
        self.assertNotIn("drive", payload["state"]["reported"])
        video_service.publish_status.assert_called_once()
        request_system_halt.assert_called_once()

    def test_main_ignores_drive_state_changes_for_shadow_publishing(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.return_code.return_value = None
        video_supervisor.read_state.return_value = _make_video_state(ready=True)
        cmd_vel_controller = MagicMock()
        cmd_vel_controller.get_drive_state.side_effect = [
            DriveState(left_speed=0, right_speed=0, sequence=0),
            DriveState(left_speed=20, right_speed=40, sequence=1),
            DriveState(left_speed=20, right_speed=40, sequence=1),
        ]

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=_make_runtime()),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(shadow_control, "_wait_for_system_clock_sync"),
            patch.object(shadow_control, "_build_cmd_vel_motor_driver", return_value=MagicMock()),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(shadow_control, "_wait_for_stop_or_halt", side_effect=[True]),
            patch.object(shadow_control, "BoardVideoService", return_value=MagicMock()),
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
            patch.object(shadow_control, "CmdVelController", return_value=cmd_vel_controller),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 2)
        first_payload = shadow_client.publish_update.call_args_list[1].args[0]
        self.assertNotIn("drive", first_payload["state"]["reported"])

    def test_build_cmd_vel_motor_driver_rejects_operational_range_above_hardware_max(self) -> None:
        with self.assertRaises(ValueError):
            _build_cmd_vel_motor_driver(
                _make_config(
                    drive_raw_max_speed=480,
                    drive_cmd_raw_min_speed=50,
                    drive_cmd_raw_max_speed=500,
                )
            )

    def test_justfile_install_service_has_no_mediamtx_dependency(self) -> None:
        justfile = Path(UNIT_BOARD_DIR / "justfile").read_text(encoding="utf-8")

        self.assertIn("--refresh-package aws --reinstall-package aws", justfile)
        self.assertIn("'Wants=network-online.target systemd-time-wait-sync.service' \\", justfile)
        self.assertIn(
            "'After=network-online.target systemd-time-wait-sync.service time-sync.target' \\",
            justfile,
        )
        self.assertNotIn("mediamtx.service", justfile)
        self.assertIn('python -m aws.check', justfile)
        self.assertIn('--scope device', justfile)
        self.assertIn('ExecStart={{built_board}} --heartbeat-seconds 60', justfile)
        self.assertIn('eval "$(just --justfile "{{root_justfile}}" _project-aws-env device', justfile)
        self.assertIn('project_root="$TXING_PROJECT_ROOT"', justfile)
        self.assertNotIn('env_file="$AWS_ENV_FILE"', justfile)
        self.assertNotIn('EnvironmentFile=$env_file', justfile)
        self.assertNotIn('EnvironmentFile=-$board_env_file', justfile)
        self.assertIn('WorkingDirectory=$project_root', justfile)
        self.assertIn('thing_name="$THING_NAME"', justfile)
        self.assertIn('schema_file="$SCHEMA_FILE"', justfile)
        self.assertIn('video_region="$BOARD_VIDEO_REGION"', justfile)
        self.assertIn('video_sender_command="$BOARD_VIDEO_SENDER_COMMAND"', justfile)
        self.assertIn('[ -n "{{thing_name}}" ]', justfile)
        self.assertIn('thing_name="{{thing_name}}"', justfile)
        self.assertIn('THING_NAME=$thing_name', justfile)
        self.assertIn('[ -n "{{schema_file}}" ]', justfile)
        self.assertIn('schema_file="{{schema_file}}"', justfile)
        self.assertIn('SCHEMA_FILE=$schema_file', justfile)
        self.assertIn('[ -n "{{video_region}}" ]', justfile)
        self.assertIn('video_region="{{video_region}}"', justfile)
        self.assertIn('BOARD_VIDEO_REGION=$video_region', justfile)
        self.assertIn('[ -n "{{video_sender_command}}" ]', justfile)
        self.assertIn('video_sender_command="{{video_sender_command}}"', justfile)
        self.assertIn('BOARD_VIDEO_SENDER_COMMAND=$video_sender_command', justfile)
        self.assertIn('[ -n "$region" ]', justfile)
        self.assertIn('AWS_REGION=$region', justfile)
        self.assertIn('AWS_DEFAULT_REGION=$region', justfile)
        self.assertIn('[ -n "$aws_profile" ]', justfile)
        self.assertNotIn('[ -n "{{aws_profile}}" ] && [ -n "$aws_profile" ]', justfile)
        self.assertIn('AWS_PROFILE=$aws_profile', justfile)
        self.assertIn('AWS_DEFAULT_PROFILE=$aws_profile', justfile)
        self.assertIn('[ -n "$aws_shared_credentials_file" ]', justfile)
        self.assertIn('AWS_SHARED_CREDENTIALS_FILE=$aws_shared_credentials_file', justfile)
        self.assertIn('for env_name in \\', justfile)
        self.assertIn('KVS_DUALSTACK_ENDPOINTS \\', justfile)
        self.assertIn('BOARD_DRIVE_RAW_MAX_SPEED \\', justfile)
        self.assertIn('BOARD_DRIVE_CMD_RAW_MIN_SPEED \\', justfile)
        self.assertIn('service_env+=("Environment=\\"$env_name=$env_value\\"")', justfile)
        self.assertNotIn('aws_config_file', justfile)
        self.assertNotIn('AWS_CONFIG_FILE=$aws_config_file', justfile)
        self.assertNotIn('AWS_TXING_PROFILE=$AWS_TXING_PROFILE', justfile)
        self.assertNotIn('lg_wd_override="{{lg_wd}}"', justfile)
        self.assertNotIn('lg_wd_configured="$lg_wd_override"', justfile)
        self.assertNotIn('lg_wd_configured="${LG_WD:-}"', justfile)
        self.assertNotIn('LG_WD=$lg_wd_override', justfile)
        self.assertNotIn('Environment="LG_WD=/tmp/txing-lgpio"', justfile)
        self.assertNotIn('BOARD_VIDEO_VIEWER_URL', justfile)
        self.assertNotIn('BOARD_VIDEO_CHANNEL_NAME', justfile)
        self.assertIn('preserve_env=(', justfile)
        self.assertIn('sudo "--preserve-env=$preserve_env_csv"', justfile)
        self.assertNotIn('LG_WD', justfile)

    def test_root_justfile_sources_consolidated_aws_env_for_device_scope(self) -> None:
        justfile = Path(REPO_ROOT / "justfile").read_text(encoding="utf-8")

        self.assertIn("_project-aws-env scope='aws'", justfile)
        self.assertIn("aws|town|rig|device", justfile)
        self.assertIn('env_file="$(resolve_path "$(choose_value "{{ env_file }}" "config/aws.env")")"', justfile)
        self.assertIn('source "$env_file"', justfile)
        self.assertIn('printf \'unset BOARD_ENV_FILE\\n\'', justfile)
        self.assertNotIn("config/board.env", justfile)
        self.assertNotIn('export_line BOARD_VIDEO_VIEWER_URL', justfile)
        self.assertNotIn('export_line LG_WD "$lg_wd"', justfile)
        self.assertIn("describe_thing_json() {", justfile)
        self.assertIn("txing_thing_id=\"$(normalize_required_slug TXING_THING_ID", justfile)
        self.assertIn("'.attributes.townId'", justfile)
        self.assertIn("'.attributes.rigId'", justfile)
        self.assertIn('export_line BOARD_DRIVE_CMD_RAW_MIN_SPEED "$board_drive_cmd_raw_min_speed"', justfile)
        self.assertIn('export_line BOARD_DRIVE_CMD_RAW_MAX_SPEED "$board_drive_cmd_raw_max_speed"', justfile)

    def test_shared_aws_check_uses_device_scope_defaults_for_thing_and_video_channel(self) -> None:
        justfile = Path(REPO_ROOT / "shared" / "aws" / "justfile").read_text(encoding="utf-8")

        self.assertIn("@check rig_id='' thing_id=''", justfile)
        self.assertIn(
            'eval "$(just --justfile "{{root_justfile}}" _project-aws-env rig "{{region}}" "{{profile}}")"',
            justfile,
        )
        self.assertIn('--scope rig', justfile)
        self.assertIn('--scope device', justfile)
        self.assertIn('--thing-name "$THING_NAME"', justfile)
        self.assertNotIn('@check thing_name=thing_name', justfile)

    def test_repo_root_detection_uses_board_working_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            board_dir = repo_root / "devices" / "unit" / "board"
            aws_dir = repo_root / "devices" / "unit" / "aws"
            board_dir.mkdir(parents=True)
            aws_dir.mkdir(parents=True)
            (board_dir / "pyproject.toml").write_text("", encoding="utf-8")
            (aws_dir / "board-shadow.schema.json").write_text("{}", encoding="utf-8")

            installed_module = (
                board_dir
                / ".venv"
                / "lib"
                / "python3.12"
                / "site-packages"
                / "board"
                / "shadow_control.py"
            )
            installed_module.parent.mkdir(parents=True)
            installed_module.write_text("", encoding="utf-8")

            detected = _discover_repo_root(
                cwd=board_dir,
                module_file=installed_module,
                env_repo_root=None,
            )

        self.assertEqual(detected, repo_root.resolve())


if __name__ == "__main__":
    unittest.main()
