from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import types
import unittest
from unittest.mock import patch


def _install_bleak_stub() -> None:
    if "bleak" in sys.modules:
        return

    bleak = types.ModuleType("bleak")
    backends = types.ModuleType("bleak.backends")
    device = types.ModuleType("bleak.backends.device")
    scanner = types.ModuleType("bleak.backends.scanner")
    exc = types.ModuleType("bleak.exc")

    class BleakClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.is_connected = False

        async def connect(self, **_kwargs: object) -> bool:
            self.is_connected = True
            return True

        async def disconnect(self) -> bool:
            self.is_connected = False
            return True

    class BleakScanner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

    class BLEDevice:
        def __init__(self, address: str, name: str | None = None) -> None:
            self.address = address
            self.name = name

    class AdvertisementData:
        def __init__(
            self,
            *,
            local_name: str | None = None,
            manufacturer_data: dict[int, bytes] | None = None,
            service_uuids: list[str] | None = None,
        ) -> None:
            self.local_name = local_name
            self.manufacturer_data = manufacturer_data or {}
            self.service_uuids = service_uuids or []

    class BleakError(Exception):
        pass

    class BleakDBusError(BleakError):
        def __init__(self, dbus_error: str = "", *args: object) -> None:
            super().__init__(*args or (dbus_error,))
            self.dbus_error = dbus_error

    bleak.BleakClient = BleakClient
    bleak.BleakScanner = BleakScanner
    device.BLEDevice = BLEDevice
    scanner.AdvertisementData = AdvertisementData
    exc.BleakError = BleakError
    exc.BleakDBusError = BleakDBusError

    sys.modules["bleak"] = bleak
    sys.modules["bleak.backends"] = backends
    sys.modules["bleak.backends.device"] = device
    sys.modules["bleak.backends.scanner"] = scanner
    sys.modules["bleak.exc"] = exc


def _install_paho_stub() -> None:
    if "paho.mqtt.client" in sys.modules:
        return

    paho = types.ModuleType("paho")
    mqtt_pkg = types.ModuleType("paho.mqtt")
    client_mod = types.ModuleType("paho.mqtt.client")

    class CallbackAPIVersion:
        VERSION2 = object()

    class MQTTMessage:
        def __init__(self) -> None:
            self.topic = ""
            self.payload = b""

    class _PublishInfo:
        rc = 0

        def wait_for_publish(self, timeout: float | None = None) -> bool:
            return True

        def is_published(self) -> bool:
            return True

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs
            self.on_connect = None
            self.on_disconnect = None
            self.on_message = None

        def tls_set(self, *args: object, **kwargs: object) -> None:
            return

        def reconnect_delay_set(self, *args: object, **kwargs: object) -> None:
            return

        def connect(self, *args: object, **kwargs: object) -> int:
            return 0

        def loop_start(self) -> None:
            return

        def loop_stop(self) -> None:
            return

        def disconnect(self) -> int:
            return 0

        def publish(self, *args: object, **kwargs: object) -> _PublishInfo:
            return _PublishInfo()

        def subscribe(self, *args: object, **kwargs: object) -> tuple[int, int]:
            return (0, 1)

    client_mod.CallbackAPIVersion = CallbackAPIVersion
    client_mod.Client = Client
    client_mod.MQTT_ERR_SUCCESS = 0
    client_mod.MQTTMessage = MQTTMessage

    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = mqtt_pkg
    sys.modules["paho.mqtt.client"] = client_mod


_install_bleak_stub()
_install_paho_stub()

from unit_rig.ble_bridge import (
    AwsShadowClient,
    AwsShadowUpdate,
    BoardVideoState,
    BleSleepBridge,
    BridgeConfig,
    RigFleetBridge,
    ShadowState,
    _build_shadow_from_snapshot,
    _calculate_redcon,
    _parse_args,
    _resolve_sparkplug_edge_node_id,
    _run_rig_service,
)
from aws.auth import ensure_aws_profile
from aws.video_topics import VIDEO_SERVICE_NAME, VIDEO_STATUS_READY
from rig.sparkplug import (
    DataType,
    build_device_report_payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    build_redcon_payload,
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

    def drain_updates(self) -> list[object]:
        return []


class ShadowPayloadTests(unittest.TestCase):
    def test_shadow_state_payload_is_reported_only_and_nested(self) -> None:
        payload = ShadowState(
            target_redcon=3,
            reported_power=True,
            battery_mv=3795,
            ble_online=True,
            board_power=True,
            board_wifi_online=True,
            redcon=2,
        ).payload()

        self.assertNotIn("desired", payload["state"])
        self.assertEqual(
            payload["state"]["reported"],
            {
                "redcon": 2,
                "device": {
                    "batteryMv": 3795,
                    "mcu": {
                        "power": True,
                        "online": True,
                    },
                    "board": {
                        "power": True,
                        "wifi": {
                            "online": True,
                        },
                    },
                },
            },
        )


class ServiceConfigTests(unittest.TestCase):
    def test_ensure_aws_profile_falls_back_to_aws_rig_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AWS_RIG_PROFILE": "rig-service",
            },
            clear=True,
        ):
            profile = ensure_aws_profile("AWS_RIG_PROFILE")

            self.assertEqual(profile, "rig-service")
            self.assertEqual(os.environ["AWS_PROFILE"], "rig-service")
            self.assertEqual(os.environ["AWS_DEFAULT_PROFILE"], "rig-service")

    def test_resolve_sparkplug_edge_node_id_prefers_rig_identity(self) -> None:
        self.assertEqual(
            _resolve_sparkplug_edge_node_id(
                rig_name="rig-alpha",
                sparkplug_edge_node_id="legacy-edge",
            ),
            "rig-alpha",
        )

    def test_resolve_sparkplug_edge_node_id_falls_back_when_rig_name_is_blank(self) -> None:
        self.assertEqual(
            _resolve_sparkplug_edge_node_id(
                rig_name="",
                sparkplug_edge_node_id="legacy-edge",
            ),
            "legacy-edge",
        )


class AwsShadowClientTests(unittest.TestCase):
    def test_configures_node_death_last_will(self) -> None:
        captured: dict[str, object] = {}

        class FakeConnection:
            def __init__(self, config: object, **kwargs: object) -> None:
                captured["config"] = config
                captured["kwargs"] = kwargs

        with patch("unit_rig.ble_bridge.AwsIotWebsocketConnection", FakeConnection):
            AwsShadowClient(
                BridgeConfig(
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="rig",
                    sparkplug_node_bdseq=77,
                ),
                aws_runtime=object(),  # type: ignore[arg-type]
            )

        config = captured["config"]
        assert isinstance(config, object)
        will_topic = getattr(config, "will_topic")
        will_payload = getattr(config, "will_payload")
        self.assertEqual(will_topic, "spBv1.0/town/NDEATH/rig")
        payload = decode_payload(will_payload)
        self.assertIsNone(payload.seq)
        self.assertEqual(len(payload.metrics), 1)
        self.assertEqual(payload.metrics[0].name, "bdSeq")
        self.assertEqual(payload.metrics[0].long_value, 77)

    def test_subscribe_topics_use_compact_startup_filters(self) -> None:
        subscribed_topics: list[tuple[str, float | None]] = []

        class FakeMqtt:
            async def subscribe(
                self,
                topic: str,
                callback: object,
                *,
                timeout_seconds: float | None = None,
            ) -> None:
                del callback
                subscribed_topics.append((topic, timeout_seconds))

        client = object.__new__(AwsShadowClient)
        client._config = BridgeConfig(
            sparkplug_group_id="town",
            sparkplug_edge_node_id="rig",
        )
        client._mqtt = FakeMqtt()
        client._managed_things = ("thing-1",)
        client._on_message = object()  # type: ignore[assignment]

        asyncio.run(client._subscribe_topics(timeout_seconds=7.5))

        self.assertEqual(
            subscribed_topics,
            [
                ("$aws/things/thing-1/shadow/get/accepted", 7.5),
                ("$aws/things/thing-1/shadow/get/rejected", 7.5),
                ("$aws/things/thing-1/shadow/update/accepted", 7.5),
                ("txings/thing-1/mcp/descriptor", 7.5),
                ("txings/thing-1/mcp/status", 7.5),
                ("txings/thing-1/video/descriptor", 7.5),
                ("txings/thing-1/video/status", 7.5),
                ("spBv1.0/town/DCMD/rig/thing-1", 7.5),
            ],
        )

    def test_initial_snapshot_bootstrap_retries_clean_session_cancelled_subscribe(self) -> None:
        instances: list[FakeConnection] = []
        accepted_payload = json.dumps(
            {
                "state": {
                    "reported": {
                        "mcu": {
                            "power": True,
                            "online": True,
                        }
                    }
                },
                "version": 7,
            }
        ).encode("utf-8")

        class FakeConnection:
            def __init__(self, _config: object, **_kwargs: object) -> None:
                self.connect_calls = 0
                self.disconnect_calls = 0
                self.subscribe_calls: list[str] = []
                self.subscriptions: dict[str, object] = {}
                instances.append(self)

            async def connect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.connect_calls += 1

            async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.disconnect_calls += 1

            async def subscribe(
                self,
                topic: str,
                callback: object,
                *,
                timeout_seconds: float | None = None,
            ) -> None:
                del timeout_seconds
                self.subscribe_calls.append(topic)
                if len(self.subscribe_calls) == 1:
                    raise RuntimeError(
                        "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION: Old requests from the previous session are cancelled"
                    )
                self.subscriptions[topic] = callback

            async def publish(
                self,
                topic: str,
                payload: bytes | str,
                *,
                retain: bool = False,
                timeout_seconds: float | None = None,
            ) -> None:
                del payload, retain, timeout_seconds
                if not topic.endswith("/shadow/get"):
                    return
                thing_name = topic.split("/")[2]
                callback = self.subscriptions[f"$aws/things/{thing_name}/shadow/get/accepted"]
                callback(
                    f"$aws/things/{thing_name}/shadow/get/accepted",
                    accepted_payload,
                )

            async def resubscribe_existing_topics(
                self,
                *,
                timeout_seconds: float | None = None,
            ) -> dict[str, list[tuple[str, int]]]:
                del timeout_seconds
                return {"topics": []}

        with patch("unit_rig.ble_bridge.AwsIotWebsocketConnection", FakeConnection):
            client = AwsShadowClient(
                BridgeConfig(),
                aws_runtime=object(),  # type: ignore[arg-type]
            )
            with patch("unit_rig.ble_bridge.LOGGER.warning") as log_warning:
                snapshots = asyncio.run(
                    client.connect_and_get_initial_snapshots(["thing-1"], timeout_seconds=5.0)
                )

        log_warning.assert_called()

        self.assertEqual(snapshots["thing-1"]["version"], 7)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].connect_calls, 2)
        self.assertEqual(instances[0].disconnect_calls, 1)
        self.assertGreaterEqual(len(instances[0].subscribe_calls), 2)

    def test_initial_snapshot_bootstrap_retries_unexpected_hangup_with_backoff(self) -> None:
        sleep_calls: list[float] = []

        class FakeConnection:
            def __init__(self, _config: object, **_kwargs: object) -> None:
                self.connect_calls = 0
                self.disconnect_calls = 0

            async def connect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.connect_calls += 1
                if self.connect_calls == 1:
                    raise RuntimeError(
                        "AWS_ERROR_MQTT_UNEXPECTED_HANGUP: The connection was closed unexpectedly."
                    )

            async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.disconnect_calls += 1

            async def subscribe(
                self,
                topic: str,
                callback: object,
                *,
                timeout_seconds: float | None = None,
            ) -> None:
                del topic, callback, timeout_seconds
                return

            async def publish(
                self,
                topic: str,
                payload: bytes | str,
                *,
                retain: bool = False,
                timeout_seconds: float | None = None,
            ) -> None:
                del topic, payload, retain, timeout_seconds
                return

            async def resubscribe_existing_topics(
                self,
                *,
                timeout_seconds: float | None = None,
            ) -> dict[str, list[tuple[str, int]]]:
                del timeout_seconds
                return {"topics": []}

        class TestAwsShadowClient(AwsShadowClient):
            async def _request_shadow_get(self, thing_name: str) -> None:
                assert self._loop is not None
                future = self._initial_snapshot_futures[thing_name]
                if not future.done():
                    future.set_result({"version": 11})

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with patch("unit_rig.ble_bridge.AwsIotWebsocketConnection", FakeConnection):
            client = TestAwsShadowClient(
                BridgeConfig(reconnect_delay=1.5),
                aws_runtime=object(),  # type: ignore[arg-type]
            )
            with patch("unit_rig.ble_bridge.asyncio.sleep", fake_sleep):
                with patch("unit_rig.ble_bridge.LOGGER.warning") as log_warning:
                    snapshots = asyncio.run(
                        client.connect_and_get_initial_snapshots(["thing-1"], timeout_seconds=5.0)
                    )

        log_warning.assert_called()
        self.assertEqual(snapshots["thing-1"]["version"], 11)
        self.assertEqual(sleep_calls, [1.5])

    def test_parse_args_accepts_service_environment_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RIG_NAME": "rig-prod",
                "SPARKPLUG_GROUP_ID": "town-prod",
                "SPARKPLUG_EDGE_NODE_ID": "rig-prod",
                "CLOUDWATCH_LOG_GROUP": "/town/rig/txing-prod",
            },
            clear=True,
        ):
            with patch("sys.argv", ["rig"]):
                args = _parse_args()

        self.assertFalse(hasattr(args, "thing_name"))
        self.assertEqual(args.rig_name, "rig-prod")
        self.assertEqual(args.sparkplug_group_id, "town-prod")
        self.assertEqual(args.sparkplug_edge_node_id, "rig-prod")
        self.assertFalse(hasattr(args, "iot_endpoint"))
        self.assertFalse(hasattr(args, "iot_endpoint_file"))
        self.assertFalse(hasattr(args, "cert_file"))
        self.assertFalse(hasattr(args, "key_file"))
        self.assertFalse(hasattr(args, "ca_file"))
        self.assertEqual(args.cloudwatch_log_group, "/town/rig/txing-prod")

    def test_justfile_install_service_exports_multi_device_environment(self) -> None:
        justfile = (Path(__file__).resolve().parents[2] / "rig" / "justfile").read_text(
            encoding="utf-8"
        )

        self.assertIn("@aws *args:", justfile)
        self.assertIn("--refresh-package aws --reinstall-package aws", justfile)
        self.assertIn('just --justfile "{{root_justfile}}" _project-aws-env rig', justfile)
        self.assertIn('command aws "$@"', justfile)
        self.assertNotIn('describe-log-groups', justfile)
        self.assertIn(
            'aws_profile="$AWS_SELECTED_PROFILE"',
            justfile,
        )
        self.assertIn(
            'aws_shared_credentials_file="$AWS_SHARED_CREDENTIALS_FILE"',
            justfile,
        )
        self.assertIn(
            'aws_config_file="$AWS_CONFIG_FILE"',
            justfile,
        )
        self.assertIn('env_file="$AWS_ENV_FILE"', justfile)
        self.assertIn('rig_env_file="$RIG_ENV_FILE"', justfile)
        self.assertIn('project_root="$TXING_PROJECT_ROOT"', justfile)
        self.assertNotIn('Environment="THING_NAME={{thing_name}}"', justfile)
        self.assertIn('rig_name="$RIG_NAME"', justfile)
        self.assertNotIn('Environment="RIG_THING_NAME={{rig_thing_name}}"', justfile)
        self.assertNotIn('Environment="TOWN_THING_NAME={{town_thing_name}}"', justfile)
        self.assertIn('sparkplug_group_id="$SPARKPLUG_GROUP_ID"', justfile)
        self.assertIn('sparkplug_edge_node_id="$SPARKPLUG_EDGE_NODE_ID"', justfile)
        self.assertIn('python -m aws.check', justfile)
        self.assertIn('--scope rig', justfile)
        self.assertNotIn('AWS_ENDPOINT_FILE', justfile)
        self.assertNotIn('IOT_ENDPOINT_FILE', justfile)
        self.assertIn('EnvironmentFile=$env_file', justfile)
        self.assertIn('EnvironmentFile=-$rig_env_file', justfile)
        self.assertIn('region="$AWS_REGION"', justfile)
        self.assertIn('[ -n "{{region}}" ]', justfile)
        self.assertIn('AWS_REGION=$region', justfile)
        self.assertIn('[ -n "{{rig_name}}" ]', justfile)
        self.assertIn('RIG_NAME=$rig_name', justfile)
        self.assertIn('[ -n "{{sparkplug_group_id}}" ]', justfile)
        self.assertIn('SPARKPLUG_GROUP_ID=$sparkplug_group_id', justfile)
        self.assertIn('[ -n "{{sparkplug_edge_node_id}}" ]', justfile)
        self.assertIn('SPARKPLUG_EDGE_NODE_ID=$sparkplug_edge_node_id', justfile)
        self.assertIn('[ -n "{{aws_profile}}" ]', justfile)
        self.assertIn('AWS_PROFILE=$aws_profile', justfile)
        self.assertIn('[ -n "{{aws_shared_credentials_file}}" ]', justfile)
        self.assertIn('AWS_SHARED_CREDENTIALS_FILE=$aws_shared_credentials_file', justfile)
        self.assertIn('[ -n "{{aws_config_file}}" ]', justfile)
        self.assertIn('AWS_CONFIG_FILE=$aws_config_file', justfile)
        self.assertIn('cloudwatch_log_group="$CLOUDWATCH_LOG_GROUP"', justfile)
        self.assertIn('[ -n "{{cloudwatch_log_group}}" ]', justfile)
        self.assertIn('CLOUDWATCH_LOG_GROUP=$cloudwatch_log_group', justfile)
        self.assertIn('WorkingDirectory=$project_root', justfile)
        self.assertIn('ExecStart={{built_rig}}', justfile)

    def test_root_justfile_sources_optional_rig_env_for_rig_scope(self) -> None:
        justfile = (Path(__file__).resolve().parents[2] / "justfile").read_text(
            encoding="utf-8"
        )

        self.assertIn("_project-aws-env scope='rig'", justfile)
        self.assertIn("rig_env_file=''", justfile)
        self.assertIn('if [ "{{scope}}" = "rig" ]; then', justfile)
        self.assertIn(
            'rig_env_file="$(resolve_path "$(choose_value "{{rig_env_file}}" "${RIG_ENV_FILE:-config/rig.env}")")"',
            justfile,
        )
        self.assertIn('source "$rig_env_file"', justfile)
        self.assertIn('export_line RIG_ENV_FILE "$rig_env_file"', justfile)

    def test_unit_rig_adapter_uses_generic_device_wording(self) -> None:
        adapter = (
            Path(__file__).resolve().parents[2]
            / "devices"
            / "unit"
            / "rig"
            / "python"
            / "src"
            / "unit_rig"
            / "ble_bridge.py"
        ).read_text(encoding="utf-8")

        self.assertIn("registered device(s) from dynamic thing group", adapter)
        self.assertIn("starting idle with no managed devices", adapter)
        self.assertIn("reported.device.mcu.online", adapter)
        self.assertIn("reported.device.board.power=false", adapter)
        self.assertNotIn("txing thing(s)", adapter)
        self.assertNotIn("managed txings", adapter)
        self.assertNotIn("into txing shadow", adapter)


class RigServiceStartupRetryTests(unittest.TestCase):
    def test_retries_transient_startup_failure(self) -> None:
        asyncio.run(self._exercise_retries_transient_startup_failure())

    async def _exercise_retries_transient_startup_failure(self) -> None:
        config = BridgeConfig(reconnect_delay=2.5)
        sleep_calls: list[float] = []
        cloud_shadows: list[FakeAwsShadowClient] = []
        fleet_bridges: list[FakeRigFleetBridge] = []

        class FakeAwsRuntime:
            def iot_client(self) -> object:
                return object()

        class FakeAwsShadowClient:
            def __init__(self, _config: BridgeConfig, _aws_runtime: object) -> None:
                self.disconnect_calls = 0
                cloud_shadows.append(self)

            async def connect_and_get_initial_snapshots(
                self,
                _thing_names: list[str] | tuple[str, ...],
                *,
                timeout_seconds: float,
            ) -> dict[str, dict[str, object]]:
                del timeout_seconds
                if len(cloud_shadows) == 1:
                    raise RuntimeError("startup failure")
                return {}

            async def disconnect(self) -> None:
                self.disconnect_calls += 1

        class FakeRegistryClient:
            def __init__(self, _iot_client: object) -> None:
                pass

            def describe_rig_in_town(
                self,
                *,
                town_name: str,
                rig_name: str,
            ) -> object:
                return types.SimpleNamespace(
                    thing_name="rig-rig001",
                    town_name=town_name,
                    rig_name=rig_name,
                )

            def list_rig_things(self, _rig_name: str) -> list[object]:
                return []

        class FakeRigFleetBridge:
            def __init__(
                self,
                _config: BridgeConfig,
                *,
                cloud_shadow: object,
                registry: object,
                managed_things: list[object],
            ) -> None:
                del cloud_shadow, registry, managed_things
                self.shutdown_calls = 0
                fleet_bridges.append(self)

            async def run(self) -> None:
                raise asyncio.CancelledError

            async def run_no_ble(self) -> None:
                raise AssertionError("run_no_ble should not be called in this test")

            async def _publish_node_death_for_shutdown(self) -> None:
                self.shutdown_calls += 1

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with patch("unit_rig.ble_bridge.LOGGER.exception") as log_exception:
            with self.assertRaises(asyncio.CancelledError):
                await _run_rig_service(
                    args_no_ble=False,
                    config=config,
                    aws_runtime=FakeAwsRuntime(),  # type: ignore[arg-type]
                    cloud_shadow_factory=FakeAwsShadowClient,
                    registry_client_factory=FakeRegistryClient,
                    fleet_bridge_factory=FakeRigFleetBridge,
                    sleep_func=fake_sleep,
                )

        log_exception.assert_called_once()

        self.assertEqual(sleep_calls, [config.reconnect_delay])
        self.assertEqual(len(cloud_shadows), 2)
        self.assertEqual([shadow.disconnect_calls for shadow in cloud_shadows], [1, 1])
        self.assertEqual(len(fleet_bridges), 1)
        self.assertEqual(fleet_bridges[0].shutdown_calls, 1)


class RigNodeReflectionTests(unittest.TestCase):
    def test_rig_node_reflection_writes_rig_shadow_when_configured(self) -> None:
        asyncio.run(self._exercise_rig_node_reflection_shadow_write())

    async def _exercise_rig_node_reflection_shadow_write(self) -> None:
        cloud_shadow = FakeCloudShadow()
        bridge = RigFleetBridge(
            BridgeConfig(rig_thing_name="rig-rig001"),
            cloud_shadow=cloud_shadow,  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            managed_things=[],
        )

        await bridge._publish_static_lifecycle_reflection()

        self.assertEqual(
            cloud_shadow.shadow_updates,
            [
                {
                    "thing_name": "rig-rig001",
                    "reported_device_patch": None,
                    "reported_root_patch": {"redcon": 1},
                }
            ],
        )
        self.assertEqual(cloud_shadow.sparkplug_publishes, [])


class RigFleetScannerTests(unittest.TestCase):
    def test_fleet_connect_waits_for_fresh_target_before_stopping_scanner(self) -> None:
        asyncio.run(self._exercise_fleet_connect_waits_for_fresh_target())

    def test_fleet_bridge_restarts_scanner_after_bridge_disconnects(self) -> None:
        asyncio.run(self._exercise_fleet_bridge_restarts_scanner())

    def test_fleet_bridge_keeps_awake_session_after_redcon_convergence(self) -> None:
        asyncio.run(self._exercise_fleet_bridge_keeps_awake_session())

    def test_bridge_needs_session_while_awake_and_disconnected(self) -> None:
        bridge = types.SimpleNamespace(
            _shadow=types.SimpleNamespace(
                target_redcon=None,
                reported_power=True,
                clear_target_redcon_if_converged=lambda: False,
            ),
            _cached_device_id="EE:C7:32:0B:1C:6A",
            _get_fresh_target_device=lambda: None,
            _is_connected=lambda: False,
        )
        fleet_bridge = RigFleetBridge(
            BridgeConfig(),
            cloud_shadow=FakeCloudShadow(),  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            managed_things=[],
        )

        self.assertTrue(fleet_bridge._bridge_needs_session(bridge))  # type: ignore[arg-type]

    async def _exercise_fleet_connect_waits_for_fresh_target(self) -> None:
        class FakeBridge:
            def __init__(self, events: list[str]) -> None:
                self._config = types.SimpleNamespace(thing_name="txing", scan_timeout=12.0)
                self._shadow = types.SimpleNamespace(target_redcon=3)
                self._cached_device_id = "EE:C7:32:0B:1C:6A"
                self._fresh_target = None
                self._events = events

            def _get_fresh_target_device(self) -> object | None:
                return self._fresh_target

            async def _wait_for_target_advertisement(
                self,
                *,
                timeout_seconds: float,
            ) -> object | None:
                self._events.append(f"wait:{timeout_seconds}")
                self._fresh_target = types.SimpleNamespace(address=self._cached_device_id)
                return self._fresh_target

            async def _ensure_connected(self) -> None:
                self._events.append("ensure")

        class TestRigFleetBridge(RigFleetBridge):
            def __init__(self, bridge: FakeBridge, events: list[str]) -> None:
                super().__init__(
                    BridgeConfig(),
                    cloud_shadow=FakeCloudShadow(),  # type: ignore[arg-type]
                    registry=object(),  # type: ignore[arg-type]
                    managed_things=[
                        types.SimpleNamespace(
                            registration=types.SimpleNamespace(
                                thing_name="txing",
                                ble_device_id=bridge._cached_device_id,
                                version=1,
                            ),
                            bridge=bridge,
                        )
                    ],
                )
                self._events = events

            async def _stop_scanner(self) -> None:
                self._events.append("stop")
                self._scanner = None

        events: list[str] = []
        bridge = FakeBridge(events)
        fleet_bridge = TestRigFleetBridge(bridge, events)

        await fleet_bridge._connect_bridge(bridge)  # type: ignore[arg-type]

        self.assertEqual(events, ["wait:12.0", "stop", "ensure"])

    async def _exercise_fleet_bridge_restarts_scanner(self) -> None:
        class FakeBridge:
            def __init__(self) -> None:
                self._connected = True
                self._shadow = types.SimpleNamespace(target_redcon=4)

            async def _process_target_redcon_once(self) -> None:
                self._connected = False
                self._shadow.target_redcon = None

            async def _safe_disconnect(self, **_: object) -> None:
                self._connected = False

            def _is_connected(self) -> bool:
                return self._connected

        class TestRigFleetBridge(RigFleetBridge):
            def __init__(self, active_bridge: FakeBridge) -> None:
                super().__init__(
                    BridgeConfig(),
                    cloud_shadow=FakeCloudShadow(),  # type: ignore[arg-type]
                    registry=object(),  # type: ignore[arg-type]
                    managed_things=[],
                )
                self._test_active_bridge = active_bridge
                self.start_calls = 0

            async def _publish_node_birth(self) -> None:
                return

            async def _normalize_startup(self) -> None:
                return

            async def _clear_converged_targets(self) -> None:
                return

            async def _reconcile_presence(self) -> None:
                return

            async def _wait_for_manager_events(
                self,
                timeout_seconds: float | None,
            ) -> list[object]:
                del timeout_seconds
                raise asyncio.CancelledError

            async def _start_scanner(self) -> None:
                self.start_calls += 1
                self._scanner = object()  # type: ignore[assignment]

            async def _stop_scanner(self) -> None:
                self._scanner = None

            def _active_bridge(self) -> FakeBridge | None:
                return self._test_active_bridge

        bridge = FakeBridge()
        fleet_bridge = TestRigFleetBridge(bridge)

        with self.assertRaises(asyncio.CancelledError):
            await fleet_bridge.run()

        self.assertEqual(fleet_bridge.start_calls, 1)

    async def _exercise_fleet_bridge_keeps_awake_session(self) -> None:
        class FakeBridge:
            def __init__(self) -> None:
                self._connected = True
                self._shadow = types.SimpleNamespace(
                    target_redcon=None,
                    reported_power=True,
                )
                self.disconnect_calls: list[dict[str, object]] = []

            async def _process_target_redcon_once(self) -> None:
                return

            async def _safe_disconnect(self, **_: object) -> None:
                self.disconnect_calls.append(dict(_))
                self._connected = False

            def _is_connected(self) -> bool:
                return self._connected

            def _should_idle_disconnected_while_sleeping(self) -> bool:
                return False

        class TestRigFleetBridge(RigFleetBridge):
            def __init__(self, active_bridge: FakeBridge) -> None:
                super().__init__(
                    BridgeConfig(),
                    cloud_shadow=FakeCloudShadow(),  # type: ignore[arg-type]
                    registry=object(),  # type: ignore[arg-type]
                    managed_things=[],
                )
                self._test_active_bridge = active_bridge
                self.start_calls = 0

            async def _publish_node_birth(self) -> None:
                return

            async def _normalize_startup(self) -> None:
                return

            async def _clear_converged_targets(self) -> None:
                return

            async def _reconcile_presence(self) -> None:
                return

            async def _wait_for_manager_events(
                self,
                timeout_seconds: float | None,
            ) -> list[object]:
                del timeout_seconds
                raise asyncio.CancelledError

            async def _start_scanner(self) -> None:
                self.start_calls += 1
                self._scanner = object()  # type: ignore[assignment]

            async def _stop_scanner(self) -> None:
                self._scanner = None

            def _active_bridge(self) -> FakeBridge | None:
                return self._test_active_bridge

        bridge = FakeBridge()
        fleet_bridge = TestRigFleetBridge(bridge)

        with self.assertRaises(asyncio.CancelledError):
            await fleet_bridge.run()

        self.assertEqual(len(bridge.disconnect_calls), 1)
        self.assertIn("disconnect_timeout_seconds", bridge.disconnect_calls[0])
        self.assertEqual(fleet_bridge.start_calls, 0)


class RedconTests(unittest.TestCase):
    def test_calculates_redcon_from_ble_mcp_and_video_posture(self) -> None:
        self.assertEqual(
            _calculate_redcon(
                ble_online=True,
                mcu_power=False,
                mcp_available=False,
                board_video_ready=False,
            ),
            4,
        )
        self.assertEqual(
            _calculate_redcon(
                ble_online=True,
                mcu_power=True,
                mcp_available=False,
                board_video_ready=False,
            ),
            3,
        )
        self.assertEqual(
            _calculate_redcon(
                ble_online=True,
                mcu_power=True,
                mcp_available=True,
                board_video_ready=False,
            ),
            2,
        )
        self.assertEqual(
            _calculate_redcon(
                ble_online=True,
                mcu_power=True,
                mcp_available=True,
                board_video_ready=True,
            ),
            1,
        )
        self.assertEqual(
            _calculate_redcon(
                ble_online=False,
                mcu_power=True,
                mcp_available=True,
                board_video_ready=True,
            ),
            4,
        )

    def test_builds_shadow_state_from_snapshot_using_registry_ble_device_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            shadow = _build_shadow_from_snapshot(
                {
                    "state": {
                        "reported": {
                            "redcon": 1,
                            "device": {
                                "batteryMv": 3795,
                                "bleDeviceId": "legacy-top-level-id",
                                "homeRig": "legacy-rig",
                                "mcu": {
                                    "power": True,
                                    "online": True,
                                },
                                "board": {
                                    "power": True,
                                    "wifi": {
                                        "online": True,
                                    },
                                },
                            },
                        },
                    },
                },
                snapshot_file=Path(tmpdir) / "shadow.json",
                registered_ble_device_id="AA:BB:CC:DD:EE:FF",
            )

        self.assertFalse(shadow.board_video_ready)
        self.assertFalse(shadow.board_video_viewer_connected)
        self.assertEqual(shadow.redcon, 1)
        self.assertEqual(shadow.ble_device_id, "AA:BB:CC:DD:EE:FF")
        payload = shadow.payload()
        reported = payload["state"]["reported"]
        self.assertNotIn("bleDeviceId", reported)
        self.assertNotIn("homeRig", reported)
        self.assertNotIn("video", reported["device"]["board"])
        self.assertEqual(
            reported["device"]["mcu"],
            {
                "power": True,
                "online": True,
            },
        )

    def test_snapshot_recovery_does_not_read_legacy_nested_ble_online(self) -> None:
        with TemporaryDirectory() as tmpdir:
            snapshot_file = Path(tmpdir) / "shadow.json"
            snapshot_file.write_text(
                json.dumps(
                    {
                        "state": {
                            "reported": {
                                "redcon": 4,
                                "device": {
                                    "batteryMv": 3795,
                                    "bleDeviceId": "AA:BB:CC:DD:EE:FF",
                                    "mcu": {
                                        "power": False,
                                        "ble": {
                                            "online": True,
                                        },
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
                            "device": {
                                "batteryMv": 3795,
                                "mcu": {
                                    "power": False,
                                    "online": False,
                                },
                            },
                        }
                    }
                },
                snapshot_file=snapshot_file,
            )

        self.assertIsNone(shadow.ble_device_id)
        self.assertFalse(shadow.ble_online)

    def test_target_redcon_only_converges_after_target_is_reached(self) -> None:
        shadow = ShadowState(target_redcon=2, redcon=3)

        self.assertFalse(shadow.clear_target_redcon_if_converged())

        shadow.redcon = 2
        self.assertTrue(shadow.clear_target_redcon_if_converged())

        shadow.target_redcon = 4
        shadow.redcon = 3
        self.assertFalse(shadow.clear_target_redcon_if_converged())

        shadow.redcon = 4
        self.assertTrue(shadow.clear_target_redcon_if_converged())


class WaitForReportedPowerTests(unittest.TestCase):
    def test_wait_for_reported_power_accepts_shadow_state_after_read_failure(self) -> None:
        asyncio.run(self._exercise_wait_for_reported_power_read_failure())

    def test_wait_for_reported_power_bounds_hung_gatt_read(self) -> None:
        asyncio.run(self._exercise_wait_for_reported_power_hung_read())

    async def _exercise_wait_for_reported_power_read_failure(self) -> None:
        shadow = ShadowState(target_redcon=3, reported_power=False, battery_mv=3729)
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

    async def _exercise_wait_for_reported_power_hung_read(self) -> None:
        shadow = ShadowState(target_redcon=3, reported_power=False, battery_mv=3729)
        bridge = BleSleepBridge(
            BridgeConfig(command_ack_timeout=0.05, command_ack_poll_interval=0.01),
            shadow,
            cloud_shadow=object(),  # type: ignore[arg-type]
        )

        class FakeClient:
            is_connected = True

        async def hang_read() -> bytes:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

        bridge._client = FakeClient()  # type: ignore[assignment]
        bridge._read_state_report = hang_read  # type: ignore[method-assign]

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await bridge._wait_for_reported_power(True)

        self.assertLess(time.monotonic() - started, 0.5)


class LifecycleBridgeTests(unittest.TestCase):
    def test_redcon_four_waits_for_board_shutdown_before_sleep(self) -> None:
        asyncio.run(self._exercise_redcon_four_board_shutdown_request())

    def test_mcp_and_video_ready_stage_redcon_through_two_before_one(self) -> None:
        asyncio.run(self._exercise_mcp_and_video_ready_stage_redcon())

    def test_viewer_connected_no_longer_changes_redcon(self) -> None:
        asyncio.run(self._exercise_viewer_connected_is_informational())

    async def _exercise_redcon_four_board_shutdown_request(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            target_redcon=4,
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

        await bridge._process_target_redcon_once()

        self.assertEqual(shadow.target_redcon, 4)
        self.assertIsNotNone(bridge._board_shutdown_requested_at)
        self.assertEqual(cloud_shadow.shadow_updates, [])

    async def _exercise_mcp_and_video_ready_stage_redcon(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            reported_power=True,
            battery_mv=3795,
            ble_online=True,
            redcon=3,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._apply_cloud_shadow_updates(
            updates=[
                AwsShadowUpdate(
                    thing_name="txing",
                    source="mqtt/mcp/status+shadow/update",
                    mcp_status={"available": True},
                    video_status={
                        "available": True,
                        "ready": True,
                        "status": VIDEO_STATUS_READY,
                        "viewerConnected": False,
                        "lastError": None,
                        "updatedAtMs": 2_000_000_000_000,
                    },
                )
            ]
        )

        self.assertTrue(shadow.mcp_available)
        self.assertTrue(shadow.board_video_ready)
        self.assertEqual(shadow.redcon, 1)
        self.assertEqual(len(cloud_shadow.shadow_updates), 2)
        first_patch = cloud_shadow.shadow_updates[0]["reported_root_patch"]
        self.assertEqual(first_patch["redcon"], 2)
        self.assertEqual(cloud_shadow.shadow_updates[1]["reported_root_patch"], {"redcon": 1})
        self.assertEqual(
            [decode_payload(payload).metrics[0].int_value for _topic, payload in cloud_shadow.sparkplug_publishes],
            [2, 1],
        )

    async def _exercise_viewer_connected_is_informational(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            reported_power=True,
            battery_mv=3795,
            ble_online=True,
            mcp_available=True,
            board_video=BoardVideoState(
                available=True,
                ready=True,
                status=VIDEO_STATUS_READY,
                updated_at_ms=2_000_000_000_000,
            ),
            redcon=1,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._apply_cloud_shadow_updates(
            updates=[
                AwsShadowUpdate(
                    thing_name="txing",
                    source="mqtt/video/status",
                    video_status={
                        "available": True,
                        "ready": True,
                        "status": VIDEO_STATUS_READY,
                        "viewerConnected": True,
                        "lastError": None,
                        "updatedAtMs": 2_000_000_000_000,
                    },
                )
            ]
        )

        self.assertTrue(shadow.board_video_viewer_connected)
        self.assertEqual(shadow.redcon, 1)
        self.assertEqual(cloud_shadow.shadow_updates, [])
        self.assertEqual(cloud_shadow.sparkplug_publishes, [])

    def test_video_status_stale_drops_redcon_back_to_two(self) -> None:
        asyncio.run(self._exercise_video_status_stale_drops_redcon())

    async def _exercise_video_status_stale_drops_redcon(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            reported_power=True,
            battery_mv=3795,
            ble_online=True,
            mcp_available=True,
            board_video=BoardVideoState(
                available=True,
                ready=True,
                status=VIDEO_STATUS_READY,
                updated_at_ms=0,
            ),
            redcon=1,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._reconcile_video_status_freshness()

        self.assertEqual(shadow.redcon, 2)
        self.assertEqual(len(cloud_shadow.shadow_updates), 1)
        self.assertEqual(cloud_shadow.shadow_updates[0]["reported_root_patch"], {"redcon": 2})

    def test_ddeath_clears_pending_target_and_publishes_device_death(self) -> None:
        asyncio.run(self._exercise_ddeath_clears_pending_target())

    async def _exercise_ddeath_clears_pending_target(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            target_redcon=3,
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
        self.assertIsNone(shadow.target_redcon)
        self.assertFalse(bridge._sparkplug_device_born)
        self.assertEqual(len(cloud_shadow.sparkplug_publishes), 1)
        self.assertEqual(
            cloud_shadow.sparkplug_publishes[0][0],
            "spBv1.0/town/DDEATH/rig/txing",
        )
        ddeath = decode_payload(cloud_shadow.sparkplug_publishes[0][1])
        self.assertEqual(ddeath.seq, 0)
        self.assertEqual(len(ddeath.metrics), 2)
        self.assertEqual(ddeath.metrics[0].name, "redcon")
        self.assertEqual(ddeath.metrics[0].int_value, 4)
        self.assertEqual(ddeath.metrics[1].name, "batteryMv")
        self.assertEqual(ddeath.metrics[1].int_value, 3812)
        self.assertEqual(len(cloud_shadow.shadow_updates), 1)
        self.assertEqual(
            cloud_shadow.shadow_updates[0]["reported_device_patch"],
            {"mcu": {"online": False}},
        )

    def test_intentional_redcon_four_offline_suppresses_ddeath(self) -> None:
        asyncio.run(self._exercise_intentional_redcon_four_offline())

    async def _exercise_intentional_redcon_four_offline(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            target_redcon=4,
            reported_power=False,
            battery_mv=3812,
            ble_online=True,
            redcon=4,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._publish_ble_online_state(
            online=False,
            context="unit-test intentional sleep",
            force=True,
        )

        self.assertFalse(shadow.ble_online)
        self.assertEqual(shadow.redcon, 4)
        self.assertEqual(shadow.target_redcon, 4)
        self.assertTrue(bridge._sparkplug_device_born)
        self.assertEqual(cloud_shadow.sparkplug_publishes, [])
        self.assertEqual(len(cloud_shadow.shadow_updates), 1)

    def test_steady_state_redcon_four_offline_suppresses_ddeath(self) -> None:
        asyncio.run(self._exercise_steady_state_redcon_four_offline())

    async def _exercise_steady_state_redcon_four_offline(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            reported_power=False,
            battery_mv=3812,
            ble_online=True,
            redcon=4,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._publish_ble_online_state(
            online=False,
            context="unit-test steady sleep",
            force=True,
        )

        self.assertFalse(shadow.ble_online)
        self.assertTrue(bridge._sparkplug_device_born)
        self.assertEqual(cloud_shadow.sparkplug_publishes, [])

    def test_online_recovery_after_intentional_sleep_does_not_duplicate_dbirth(self) -> None:
        asyncio.run(self._exercise_intentional_sleep_online_recovery())

    async def _exercise_intentional_sleep_online_recovery(self) -> None:
        cloud_shadow = FakeCloudShadow()
        shadow = ShadowState(
            reported_power=False,
            battery_mv=3812,
            ble_online=False,
            redcon=4,
        )
        bridge = BleSleepBridge(
            BridgeConfig(),
            shadow,
            cloud_shadow,  # type: ignore[arg-type]
        )
        bridge._sparkplug_device_born = True

        await bridge._publish_ble_online_state(
            online=True,
            context="unit-test intentional sleep recovery",
            force=True,
        )

        self.assertTrue(shadow.ble_online)
        self.assertEqual(cloud_shadow.sparkplug_publishes, [])

    def test_node_death_publishes_once_after_birth(self) -> None:
        asyncio.run(self._exercise_node_death_once_after_birth())

    async def _exercise_node_death_once_after_birth(self) -> None:
        cloud_shadow = FakeCloudShadow()
        bridge = BleSleepBridge(
            BridgeConfig(sparkplug_node_bdseq=41),
            ShadowState(),
            cloud_shadow,  # type: ignore[arg-type]
        )

        await bridge._publish_node_birth()
        await bridge._publish_node_death()
        await bridge._publish_node_death()

        self.assertEqual(len(cloud_shadow.sparkplug_publishes), 2)
        self.assertEqual(
            [topic for topic, _payload in cloud_shadow.sparkplug_publishes],
            [
                "spBv1.0/town/NBIRTH/rig",
                "spBv1.0/town/NDEATH/rig",
            ],
        )
        birth = decode_payload(cloud_shadow.sparkplug_publishes[0][1])
        self.assertEqual(birth.seq, 0)
        self.assertEqual(
            [(metric.name, metric.long_value, metric.int_value) for metric in birth.metrics],
            [("bdSeq", 41, None), ("rig.redcon", None, 1)],
        )
        death = decode_payload(cloud_shadow.sparkplug_publishes[1][1])
        self.assertIsNone(death.seq)
        self.assertEqual(
            [(metric.name, metric.long_value, metric.int_value) for metric in death.metrics],
            [("bdSeq", 41, None)],
        )


class SnapshotRecoveryTests(unittest.TestCase):
    def test_restart_does_not_recover_target_redcon_from_local_cache(self) -> None:
        with TemporaryDirectory() as tmpdir:
            snapshot_file = Path(tmpdir) / "shadow.json"
            snapshot_file.write_text(
                json.dumps(
                    {
                        "state": {
                            "reported": {
                                "redcon": 4,
                                "device": {
                                    "batteryMv": 3795,
                                    "mcu": {
                                        "power": False,
                                        "online": False,
                                    },
                                    "board": {
                                        "power": False,
                                        "wifi": {
                                            "online": False,
                                        },
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
                            "device": {
                                "batteryMv": 3795,
                                "mcu": {
                                    "power": False,
                                    "online": False,
                                },
                            },
                        }
                    }
                },
                snapshot_file=snapshot_file,
            )

        self.assertIsNone(shadow.target_redcon)


class SparkplugCodecTests(unittest.TestCase):
    def test_decodes_redcon_command_payload(self) -> None:
        command = decode_redcon_command(build_redcon_payload(redcon=3, seq=5))

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.metric_name, "redcon")
        self.assertEqual(command.value, 3)
        self.assertEqual(command.seq, 5)

    def test_encodes_node_birth_payload(self) -> None:
        topic = build_node_topic("town", "NBIRTH", "rig")
        payload = decode_payload(
            build_node_birth_payload(
                redcon=1,
                bdseq=123,
                seq=9,
            )
        )

        self.assertEqual(topic, "spBv1.0/town/NBIRTH/rig")
        self.assertEqual(payload.seq, 9)
        self.assertEqual(payload.metrics[0].name, "bdSeq")
        self.assertEqual(payload.metrics[0].datatype, DataType.UINT64)
        self.assertEqual(payload.metrics[0].long_value, 123)
        self.assertEqual(payload.metrics[1].name, "rig.redcon")
        self.assertEqual(payload.metrics[1].int_value, 1)

    def test_encodes_node_death_payload(self) -> None:
        topic = build_node_topic("town", "NDEATH", "rig")
        payload = decode_payload(build_node_death_payload(bdseq=123))

        self.assertEqual(topic, "spBv1.0/town/NDEATH/rig")
        self.assertIsNone(payload.seq)
        self.assertEqual(len(payload.metrics), 1)
        self.assertEqual(payload.metrics[0].name, "bdSeq")
        self.assertEqual(payload.metrics[0].long_value, 123)

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

        payload = decode_payload(
            build_device_report_payload(
                redcon=2,
                battery_mv=3777,
                seq=11,
            )
        )

        self.assertEqual(payload.seq, 11)
        self.assertEqual(len(payload.metrics), 2)
        self.assertEqual(payload.metrics[0].name, "redcon")
        self.assertEqual(payload.metrics[0].int_value, 2)
        self.assertEqual(payload.metrics[1].name, "batteryMv")
        self.assertEqual(payload.metrics[1].int_value, 3777)


if __name__ == "__main__":
    unittest.main()
