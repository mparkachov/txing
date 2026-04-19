from __future__ import annotations

from argparse import Namespace
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from board.cmd_vel import DriveState, build_cmd_vel_topic
from board.shadow_control import (
    AwsShadowClient,
    DEFAULT_AWS_CONNECT_TIMEOUT,
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_MQTT_PUBLISH_TIMEOUT,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_TIME_SYNC_TIMEOUT,
    DEFAULT_VIDEO_REGION,
    DEFAULT_VIDEO_STARTUP_TIMEOUT_SECONDS,
    ControlConfig,
    DefaultRouteAddresses,
    REPO_ROOT,
    VideoStartupTimeoutError,
    _build_board_report,
    _build_cmd_vel_motor_driver,
    _build_shutdown_board_report,
    _build_shadow_update_with_options,
    _discover_repo_root,
    _extract_desired_board_power_from_delta,
    _extract_desired_board_power_from_shadow,
    _load_validator,
    _validate_shadow_update,
    _wait_for_system_clock_sync,
    _wait_for_video_ready,
)
from board.video_state import DEFAULT_VIDEO_CHANNEL_NAME, build_reported_video_state
import board.shadow_control as shadow_control

UNIT_AWS_DIR = REPO_ROOT / "devices" / "unit" / "aws"
UNIT_BOARD_DIR = REPO_ROOT / "devices" / "unit" / "board"


def _make_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "shadow_file": Path("/tmp/unit_board_shadow.json"),
        "thing_name": "unit-local",
        "schema_file": Path(UNIT_AWS_DIR / "shadow.schema.json"),
        "client_id": None,
        "video_channel_name": DEFAULT_VIDEO_CHANNEL_NAME,
        "video_viewer_url": "https://ops.example.com/video",
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
        "session": {
            "viewerUrl": "https://ops.example.com/video",
            "channelName": "unit-local-board-video",
        },
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
        "schema_file": Path(UNIT_AWS_DIR / "shadow.schema.json"),
        "shadow_file": Path("/tmp/unit_board_shadow.json"),
        "client_id": "bot-board-test",
        "video_channel_name": DEFAULT_VIDEO_CHANNEL_NAME,
        "video_viewer_url": "https://ops.example.com/video",
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
        "once": False,
    }
    values.update(overrides)
    return ControlConfig(**values)


class ShadowControlContractTests(unittest.TestCase):
    def test_routes_cmd_vel_messages_to_controller(self) -> None:
        cmd_vel_controller = MagicMock()
        shadow_client = AwsShadowClient(
            _make_config(),
            aws_runtime=MagicMock(),
            cmd_vel_controller=cmd_vel_controller,
        )

        shadow_client._on_message(
            build_cmd_vel_topic("unit-local"),
            json.dumps(
                {
                    "linear": {"x": 1, "y": 0, "z": 0},
                    "angular": {"x": 0, "y": 0, "z": 0},
                }
            ).encode("utf-8"),
        )

        cmd_vel_controller.handle_message.assert_called_once_with(
            {
                "linear": {"x": 1, "y": 0, "z": 0},
                "angular": {"x": 0, "y": 0, "z": 0},
            }
        )

    def test_extracts_desired_board_power_from_shadow_snapshot(self) -> None:
        payload = {
            "state": {
                "desired": {
                    "board": {
                        "power": False,
                    }
                }
            }
        }

        self.assertIs(_extract_desired_board_power_from_shadow(payload), False)

    def test_extracts_desired_board_power_from_delta(self) -> None:
        payload = {
            "state": {
                "board": {
                    "power": False,
                }
            }
        }

        self.assertIs(_extract_desired_board_power_from_delta(payload), False)

    def test_shutdown_update_clears_desired_board_power(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "shadow.schema.json"))
        payload = _build_shadow_update_with_options(
            report=_build_shutdown_board_report(),
            clear_desired_power=True,
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 0)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 0)

    def test_board_report_with_video_matches_schema(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "shadow.schema.json"))
        report = _build_board_report(
            addresses=type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": "2001:db8::20"})(),
            power=True,
            drive_state=DriveState(left_speed=20, right_speed=30, sequence=1),
            video_state=_make_video_state(ready=True),
        )

        _validate_shadow_update(validator, {"state": {"reported": {"board": report}}})
        self.assertEqual(report["video"]["session"]["channelName"], "unit-local-board-video")
        self.assertEqual(report["drive"]["leftSpeed"], 20)
        self.assertEqual(report["drive"]["rightSpeed"], 30)

    def test_default_shadow_reset_payload_matches_schema(self) -> None:
        validator = _load_validator(Path(UNIT_AWS_DIR / "shadow.schema.json"))
        payload = json.loads(
            Path(UNIT_AWS_DIR / "default-shadow.json").read_text(encoding="utf-8")
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["redcon"])
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertEqual(payload["state"]["reported"]["redcon"], 4)
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 0)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 0)

    def test_reported_video_state_omits_runtime_timestamp(self) -> None:
        reported = build_reported_video_state(
            {
                "status": "ready",
                "ready": True,
                "transport": "aws-webrtc",
                "session": {
                    "viewerUrl": "https://ops.example.com/video",
                    "channelName": "unit-local-board-video",
                },
                "codec": {
                    "video": "h264",
                },
                "viewerConnected": False,
                "lastError": None,
                "updatedAt": "2026-03-25T12:00:00Z",
            }
        )

        self.assertNotIn("updatedAt", reported)

    def test_wait_for_video_ready_times_out_when_sender_never_becomes_ready(self) -> None:
        config = _make_config(video_startup_timeout_seconds=0.0)
        stop_event = threading.Event()
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        video_supervisor = MagicMock()
        video_supervisor.return_code.return_value = None

        with (
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6=None),
            ),
            patch.object(
                shadow_control,
                "_read_video_state",
                return_value=_make_video_state(ready=False, last_error="video sender boot failed"),
            ),
        ):
            with self.assertRaises(VideoStartupTimeoutError):
                _wait_for_video_ready(stop_event, shadow_client, config, video_supervisor)

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

    def test_main_once_waits_for_video_ready_before_first_publish(self) -> None:
        args = _make_args(once=True)
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.return_code.return_value = None
        video_supervisor.read_state.side_effect = [
            _make_video_state(ready=False, last_error="sender warming up"),
            _make_video_state(ready=True),
        ]

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=MagicMock(iot_data_endpoint=MagicMock(return_value="example-ats.iot.eu-central-1.amazonaws.com"))),
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
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
            patch.object(shadow_control, "DEFAULT_VIDEO_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(video_supervisor.read_state.call_count, 2)
        self.assertEqual(shadow_client.publish_update.call_count, 1)
        payload = shadow_client.publish_update.call_args.args[0]
        self.assertEqual(payload["state"]["reported"]["board"]["video"]["status"], "ready")
        self.assertIs(payload["state"]["reported"]["board"]["video"]["ready"], True)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 0)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 0)

    def test_main_publishes_runtime_video_error_after_successful_start(self) -> None:
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

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=MagicMock(iot_data_endpoint=MagicMock(return_value="example-ats.iot.eu-central-1.amazonaws.com"))),
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
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
            patch.object(shadow_control, "DEFAULT_VIDEO_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 2)
        first_payload = shadow_client.publish_update.call_args_list[0].args[0]
        second_payload = shadow_client.publish_update.call_args_list[1].args[0]
        self.assertEqual(first_payload["state"]["reported"]["board"]["video"]["status"], "ready")
        self.assertEqual(second_payload["state"]["reported"]["board"]["video"]["status"], "error")
        self.assertIs(second_payload["state"]["reported"]["board"]["video"]["ready"], False)
        self.assertEqual(
            second_payload["state"]["reported"]["board"]["video"]["lastError"],
            "video sender exited",
        )

    def test_main_honors_halt_requested_during_video_startup_gate(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.side_effect = [False, False, True, True]
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True
        video_supervisor = MagicMock()
        video_supervisor.return_code.return_value = None
        video_supervisor.read_state.return_value = _make_video_state(
            ready=False,
            last_error="video sender boot failed",
        )

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(shadow_control, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(shadow_control, "build_aws_runtime", return_value=MagicMock(iot_data_endpoint=MagicMock(return_value="example-ats.iot.eu-central-1.amazonaws.com"))),
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
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
            patch.object(shadow_control, "DEFAULT_VIDEO_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 1)
        payload = shadow_client.publish_update.call_args.args[0]
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 0)
        self.assertEqual(payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 0)
        request_system_halt.assert_called_once()

    def test_main_publishes_drive_state_changes_before_heartbeat(self) -> None:
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
            patch.object(shadow_control, "build_aws_runtime", return_value=MagicMock(iot_data_endpoint=MagicMock(return_value="example-ats.iot.eu-central-1.amazonaws.com"))),
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
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "VideoSenderSupervisor", return_value=video_supervisor),
            patch.object(shadow_control, "CmdVelController", return_value=cmd_vel_controller),
            patch.object(shadow_control, "DEFAULT_VIDEO_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 2)
        first_payload = shadow_client.publish_update.call_args_list[0].args[0]
        second_payload = shadow_client.publish_update.call_args_list[1].args[0]
        self.assertEqual(first_payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 0)
        self.assertEqual(first_payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 0)
        self.assertEqual(second_payload["state"]["reported"]["board"]["drive"]["leftSpeed"], 20)
        self.assertEqual(second_payload["state"]["reported"]["board"]["drive"]["rightSpeed"], 40)

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
        self.assertIn('env_file="$AWS_ENV_FILE"', justfile)
        self.assertIn('board_env_file="$BOARD_ENV_FILE"', justfile)
        self.assertIn('EnvironmentFile=$env_file', justfile)
        self.assertIn('EnvironmentFile=-$board_env_file', justfile)
        self.assertIn('WorkingDirectory=$project_root', justfile)
        self.assertIn('[ -n "{{thing_name}}" ]', justfile)
        self.assertIn('THING_NAME={{thing_name}}', justfile)
        self.assertIn('[ -n "{{schema_file}}" ]', justfile)
        self.assertIn('SCHEMA_FILE={{schema_file}}', justfile)
        self.assertIn('[ -n "{{video_viewer_url}}" ]', justfile)
        self.assertIn('BOARD_VIDEO_VIEWER_URL={{video_viewer_url}}', justfile)
        self.assertIn('[ -n "{{video_region}}" ]', justfile)
        self.assertIn('BOARD_VIDEO_REGION={{video_region}}', justfile)
        self.assertIn('[ -n "{{video_channel_name}}" ]', justfile)
        self.assertIn('BOARD_VIDEO_CHANNEL_NAME={{video_channel_name}}', justfile)
        self.assertIn('[ -n "{{video_sender_command}}" ]', justfile)
        self.assertIn('BOARD_VIDEO_SENDER_COMMAND={{video_sender_command}}', justfile)
        self.assertIn('[ -n "{{region}}" ] && [ -n "$region" ]', justfile)
        self.assertIn('AWS_REGION=$region', justfile)
        self.assertIn('[ -n "{{aws_profile}}" ] && [ -n "$aws_profile" ]', justfile)
        self.assertIn('AWS_PROFILE=$aws_profile', justfile)
        self.assertIn('AWS_DEFAULT_PROFILE=$aws_profile', justfile)
        self.assertIn('[ -n "{{aws_shared_credentials_file}}" ] && [ -n "$aws_shared_credentials_file" ]', justfile)
        self.assertIn('AWS_SHARED_CREDENTIALS_FILE=$aws_shared_credentials_file', justfile)
        self.assertIn('[ -n "{{aws_config_file}}" ] && [ -n "$aws_config_file" ]', justfile)
        self.assertIn('AWS_CONFIG_FILE=$aws_config_file', justfile)
        self.assertNotIn('AWS_TXING_PROFILE=$AWS_TXING_PROFILE', justfile)
        self.assertIn('lg_wd_override="{{lg_wd}}"', justfile)
        self.assertIn('lg_wd_configured="$lg_wd_override"', justfile)
        self.assertIn('lg_wd_configured="${LG_WD:-}"', justfile)
        self.assertIn('[ -n "$lg_wd_configured" ]', justfile)
        self.assertIn('[ -n "$lg_wd_override" ]', justfile)
        self.assertIn('LG_WD=$lg_wd_override', justfile)
        self.assertNotIn('Environment="LG_WD=/tmp/txing-lgpio"', justfile)
        self.assertIn('preserve_env=(', justfile)
        self.assertIn('sudo "--preserve-env=$preserve_env_csv"', justfile)

    def test_root_justfile_sources_optional_board_env_for_device_scope(self) -> None:
        justfile = Path(REPO_ROOT / "justfile").read_text(encoding="utf-8")

        self.assertIn("_project-aws-env scope='rig'", justfile)
        self.assertIn('board_env_file=\'\'', justfile)
        self.assertIn('env_file="$(resolve_path "$(choose_value "{{env_file}}" "config/aws.env")")"', justfile)
        self.assertIn('if [ "{{scope}}" = "device" ]; then', justfile)
        self.assertIn('board_env_file="$(resolve_path "$(choose_value "{{board_env_file}}" "${BOARD_ENV_FILE:-config/board.env}")")"', justfile)
        self.assertIn('source "$board_env_file"', justfile)
        self.assertIn('export_line BOARD_ENV_FILE "$board_env_file"', justfile)
        self.assertIn('export_line LG_WD "$lg_wd"', justfile)
        self.assertIn('export_line BOARD_DRIVE_CMD_RAW_MIN_SPEED "$board_drive_cmd_raw_min_speed"', justfile)
        self.assertIn('export_line BOARD_DRIVE_CMD_RAW_MAX_SPEED "$board_drive_cmd_raw_max_speed"', justfile)

    def test_repo_root_detection_uses_board_working_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            board_dir = repo_root / "devices" / "unit" / "board"
            aws_dir = repo_root / "devices" / "unit" / "aws"
            board_dir.mkdir(parents=True)
            aws_dir.mkdir(parents=True)
            (board_dir / "pyproject.toml").write_text("", encoding="utf-8")
            (aws_dir / "shadow.schema.json").write_text("{}", encoding="utf-8")

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
