from __future__ import annotations

from argparse import Namespace
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from board.media_runtime import DEFAULT_PROBE_HOST
from board.media_state import (
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_STREAM_PATH,
    build_reported_media_state,
)
from board.shadow_control import (
    DEFAULT_AWS_CONNECT_TIMEOUT,
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_MEDIA_STARTUP_TIMEOUT_SECONDS,
    DEFAULT_MQTT_PUBLISH_TIMEOUT,
    DEFAULT_RECONNECT_DELAY,
    ControlConfig,
    DefaultRouteAddresses,
    MediaStartupTimeoutError,
    REPO_ROOT,
    _build_board_report,
    _build_shutdown_board_report,
    _build_shadow_update_with_options,
    _discover_repo_root,
    _extract_desired_board_power_from_delta,
    _extract_desired_board_power_from_shadow,
    _load_validator,
    _validate_shadow_update,
    _wait_for_media_ready,
)
import board.shadow_control as shadow_control


def _make_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "shadow_file": Path("/tmp/txing_board_shadow.json"),
        "thing_name": "txing",
        "iot_endpoint": None,
        "iot_endpoint_file": Path("/tmp/iot-data-ats.endpoint"),
        "cert_file": Path("/tmp/txing.cert.pem"),
        "key_file": Path("/tmp/txing.private.key"),
        "ca_file": Path("/tmp/AmazonRootCA1.pem"),
        "schema_file": Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"),
        "client_id": None,
        "stream_path": DEFAULT_STREAM_PATH,
        "viewer_port": DEFAULT_MEDIAMTX_VIEWER_PORT,
        "viewer_host": "",
        "probe_host": DEFAULT_PROBE_HOST,
        "probe_timeout_seconds": 0.1,
        "media_startup_timeout_seconds": DEFAULT_MEDIA_STARTUP_TIMEOUT_SECONDS,
        "board_name": "txing-board-test",
        "heartbeat_seconds": DEFAULT_HEARTBEAT_SECONDS,
        "aws_connect_timeout": DEFAULT_AWS_CONNECT_TIMEOUT,
        "publish_timeout": DEFAULT_MQTT_PUBLISH_TIMEOUT,
        "reconnect_delay": DEFAULT_RECONNECT_DELAY,
        "halt_command": ["/bin/true"],
        "once": False,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _make_media_state(*, ready: bool, last_error: str | None = None) -> dict[str, object]:
    return {
        "status": "ready" if ready else "error",
        "ready": ready,
        "local": {
            "viewerUrl": "http://192.168.1.20:8889/board-cam/",
            "streamPath": "board-cam",
        },
        "codec": {
            "video": "h264",
        },
        "viewerConnected": False,
        "lastError": last_error,
    }


def _make_config(**overrides: object) -> ControlConfig:
    values: dict[str, object] = {
        "thing_name": "txing",
        "iot_endpoint": "example-ats.iot.eu-central-1.amazonaws.com",
        "cert_file": Path("/tmp/txing.cert.pem"),
        "key_file": Path("/tmp/txing.private.key"),
        "ca_file": Path("/tmp/AmazonRootCA1.pem"),
        "schema_file": Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"),
        "shadow_file": Path("/tmp/txing_board_shadow.json"),
        "client_id": "txing-board-test",
        "stream_path": DEFAULT_STREAM_PATH,
        "viewer_port": DEFAULT_MEDIAMTX_VIEWER_PORT,
        "viewer_host": "",
        "probe_host": DEFAULT_PROBE_HOST,
        "probe_timeout_seconds": 0.1,
        "media_startup_timeout_seconds": DEFAULT_MEDIA_STARTUP_TIMEOUT_SECONDS,
        "board_name": "txing-board-test",
        "heartbeat_seconds": DEFAULT_HEARTBEAT_SECONDS,
        "aws_connect_timeout": DEFAULT_AWS_CONNECT_TIMEOUT,
        "publish_timeout": DEFAULT_MQTT_PUBLISH_TIMEOUT,
        "reconnect_delay": DEFAULT_RECONNECT_DELAY,
        "halt_command": ("/bin/true",),
        "once": False,
    }
    values.update(overrides)
    return ControlConfig(**values)


class ShadowControlContractTests(unittest.TestCase):
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
        validator = _load_validator(Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"))
        payload = _build_shadow_update_with_options(
            report=_build_shutdown_board_report(),
            clear_desired_power=True,
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)

    def test_board_report_with_video_matches_schema(self) -> None:
        validator = _load_validator(Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"))
        report = _build_board_report(
            addresses=type("Addresses", (), {"ipv4": "192.168.1.20", "ipv6": "2001:db8::20"})(),
            power=True,
            media_state={
                "status": "ready",
                "ready": True,
                "local": {
                    "viewerUrl": "http://192.168.1.20:8889/board-cam/",
                    "streamPath": "board-cam",
                },
                "codec": {
                    "video": "h264",
                },
                "viewerConnected": False,
                "lastError": None,
            },
        )

        _validate_shadow_update(validator, {"state": {"reported": {"board": report}}})
        self.assertEqual(report["video"]["local"]["streamPath"], "board-cam")

    def test_default_shadow_reset_payload_matches_schema(self) -> None:
        validator = _load_validator(Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"))
        payload = json.loads(
            Path(REPO_ROOT / "aws" / "default-shadow.json").read_text(encoding="utf-8")
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["mcu"]["power"])
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertIs(payload["state"]["reported"]["mcu"]["power"], False)
        self.assertIs(payload["state"]["reported"]["mcu"]["ble"]["online"], False)
        self.assertIsNone(payload["state"]["reported"]["mcu"]["ble"]["deviceId"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)

    def test_reported_media_state_omits_runtime_timestamp(self) -> None:
        reported = build_reported_media_state(
            {
                "status": "ready",
                "ready": True,
                "local": {
                    "viewerUrl": "http://192.168.1.20:8889/board-cam/",
                    "streamPath": "board-cam",
                },
                "codec": {
                    "video": "h264",
                },
                "viewerConnected": False,
                "lastError": None,
                "updatedAt": "2026-03-20T12:00:00Z",
            }
        )

        self.assertNotIn("updatedAt", reported)

    def test_wait_for_media_ready_times_out_when_media_never_becomes_ready(self) -> None:
        config = _make_config(media_startup_timeout_seconds=0.0)
        stop_event = threading.Event()
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False

        with (
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6=None),
            ),
            patch.object(
                shadow_control,
                "_build_live_media_state_from_config",
                return_value=_make_media_state(ready=False, last_error="MediaMTX probe failed"),
            ),
        ):
            with self.assertRaises(MediaStartupTimeoutError):
                _wait_for_media_ready(stop_event, shadow_client, config)

    def test_main_once_waits_for_media_ready_before_first_publish(self) -> None:
        args = _make_args(once=True)
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(
                shadow_control,
                "_read_iot_endpoint",
                return_value="example-ats.iot.eu-central-1.amazonaws.com",
            ),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(
                shadow_control,
                "_build_live_media_state_from_config",
                side_effect=[
                    _make_media_state(ready=False, last_error="MediaMTX probe failed"),
                    _make_media_state(ready=True),
                ],
            ) as build_media_state,
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "DEFAULT_MEDIA_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(build_media_state.call_count, 2)
        self.assertEqual(shadow_client.publish_update.call_count, 1)
        payload = shadow_client.publish_update.call_args.args[0]
        self.assertEqual(payload["state"]["reported"]["board"]["video"]["status"], "ready")
        self.assertIs(payload["state"]["reported"]["board"]["video"]["ready"], True)

    def test_main_publishes_runtime_media_error_after_successful_start(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.return_value = False
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(
                shadow_control,
                "_read_iot_endpoint",
                return_value="example-ats.iot.eu-central-1.amazonaws.com",
            ),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(
                shadow_control,
                "_build_live_media_state_from_config",
                side_effect=[
                    _make_media_state(ready=True),
                    _make_media_state(ready=False, last_error="MediaMTX probe failed"),
                ],
            ),
            patch.object(shadow_control, "_wait_for_stop_or_halt", side_effect=[False, True]),
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "DEFAULT_MEDIA_READY_POLL_INTERVAL", 0.0),
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
            "MediaMTX probe failed",
        )

    def test_main_honors_halt_requested_during_media_startup_gate(self) -> None:
        args = _make_args()
        shadow_client = MagicMock()
        shadow_client.halt_requested.side_effect = [False, False, True, True]
        shadow_client.publish_update.return_value = {"state": {}}
        shadow_client.is_connected.return_value = True

        with (
            patch.object(shadow_control, "_parse_args", return_value=args),
            patch.object(shadow_control, "_configure_logging"),
            patch.object(
                shadow_control,
                "_read_iot_endpoint",
                return_value="example-ats.iot.eu-central-1.amazonaws.com",
            ),
            patch.object(shadow_control, "_require_file"),
            patch.object(shadow_control, "_load_validator", return_value=object()),
            patch.object(shadow_control, "_install_signal_handlers"),
            patch.object(shadow_control, "_validate_shadow_update"),
            patch.object(shadow_control, "save_shadow"),
            patch.object(
                shadow_control,
                "_detect_default_route_addresses",
                return_value=DefaultRouteAddresses(ipv4="192.168.1.20", ipv6="2001:db8::20"),
            ),
            patch.object(
                shadow_control,
                "_build_live_media_state_from_config",
                return_value=_make_media_state(ready=False, last_error="MediaMTX probe failed"),
            ),
            patch.object(shadow_control, "_request_system_halt") as request_system_halt,
            patch.object(shadow_control, "AwsShadowClient", return_value=shadow_client),
            patch.object(shadow_control, "DEFAULT_MEDIA_READY_POLL_INTERVAL", 0.0),
        ):
            shadow_control.main()

        self.assertEqual(shadow_client.publish_update.call_count, 1)
        payload = shadow_client.publish_update.call_args.args[0]
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        request_system_halt.assert_called_once()

    def test_justfile_install_service_depends_on_mediamtx_only(self) -> None:
        justfile = Path(REPO_ROOT / "board" / "justfile").read_text(encoding="utf-8")

        self.assertIn("'Wants=network-online.target mediamtx.service' \\", justfile)
        self.assertIn("'After=network-online.target mediamtx.service' \\", justfile)
        self.assertNotIn("txing-board-media.service", justfile)
        self.assertNotIn("@install-media-service", justfile)

    def test_repo_root_detection_uses_board_working_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            board_dir = repo_root / "board"
            docs_dir = repo_root / "docs"
            board_dir.mkdir()
            docs_dir.mkdir()
            (board_dir / "pyproject.toml").write_text("", encoding="utf-8")
            (docs_dir / "txing-shadow.schema.json").write_text("{}", encoding="utf-8")

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
