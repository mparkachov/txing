from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import patch

from rig.connectivity_protocol import (
    CONTROL_EVENTUAL,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    SLEEP_MODEL_MATTER_ICD,
    TRANSPORT_BLE_GATT,
    TRANSPORT_MATTER,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import decode_payload
from unit_rig.ble_bridge import AwsShadowUpdate, BridgeConfig
from unit_rig.sparkplug_manager import (
    DeviceSparkplugMqttSession,
    ManagedDeviceState,
    SparkplugManager,
    SparkplugMqttSessionConfig,
    _build_bridge_config,
    _parse_args,
    run_sparkplug_manager,
)
from unit_rig.thing_registry import ThingRegistration


class FakeCloudClient:
    def __init__(self) -> None:
        self.named_shadow_updates: list[dict[str, object]] = []
        self.sparkplug_publishes: list[tuple[str, bytes]] = []
        self.disconnect_calls = 0

    async def update_named_shadow_reported(self, **kwargs: object) -> None:
        self.named_shadow_updates.append(kwargs)

    async def publish_sparkplug(self, topic: str, payload: bytes, **_: object) -> None:
        self.sparkplug_publishes.append((topic, payload))

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class FakeDeviceSession:
    def __init__(
        self,
        _config: SparkplugMqttSessionConfig,
        *,
        thing_name: str,
        aws_runtime: object,
    ) -> None:
        del aws_runtime
        self.thing_name = thing_name
        self.connected = False
        self.born = False
        self.births: list[tuple[int, int]] = []
        self.data: list[tuple[int, int]] = []
        self.deaths = 0
        self.disconnects = 0

    async def publish_birth(self, *, redcon: int, battery_mv: int) -> None:
        self.connected = True
        self.born = True
        self.births.append((redcon, battery_mv))

    async def publish_data(self, *, redcon: int, battery_mv: int) -> None:
        self.data.append((redcon, battery_mv))

    async def teardown(self, *, explicit_death: bool) -> None:
        if explicit_death:
            self.deaths += 1
        self.connected = False
        self.born = False
        self.disconnects += 1


class FailingBirthOnceDeviceSession(FakeDeviceSession):
    def __init__(
        self,
        config: SparkplugMqttSessionConfig,
        *,
        thing_name: str,
        aws_runtime: object,
    ) -> None:
        super().__init__(config, thing_name=thing_name, aws_runtime=aws_runtime)
        self.fail_birth = True

    async def publish_birth(self, *, redcon: int, battery_mv: int) -> None:
        if self.fail_birth:
            self.fail_birth = False
            raise RuntimeError("transient connect hangup")
        await super().publish_birth(redcon=redcon, battery_mv=battery_mv)


class FakeAwsRuntime:
    def iot_client(self) -> object:
        return object()

    def iot_data_endpoint(self) -> str:
        return "endpoint"


class EndpointShouldNotBeDiscoveredRuntime(FakeAwsRuntime):
    def iot_data_endpoint(self) -> str:
        raise AssertionError("endpoint discovery should not be called")


class FakeRegistryClient:
    def __init__(self, registrations: list[ThingRegistration]) -> None:
        self._registrations = registrations

    def list_rig_things(self, rig_name: str) -> list[ThingRegistration]:
        self.rig_name = rig_name
        return list(self._registrations)


class FakeLifecycleCloud(FakeCloudClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []
        self.node_birth_published = asyncio.Event()

    async def connect_and_get_initial_snapshots(
        self,
        thing_capabilities: dict[str, tuple[str, ...]],
        *,
        timeout_seconds: float,
    ) -> dict[str, dict[str, object]]:
        del timeout_seconds
        self.events.append("connect")
        return {thing_name: {} for thing_name in thing_capabilities}

    async def publish_sparkplug(self, topic: str, payload: bytes, **kwargs: object) -> None:
        await super().publish_sparkplug(topic, payload, **kwargs)
        self.events.append(topic)
        if topic == "spBv1.0/town/NBIRTH/rig":
            self.node_birth_published.set()

    async def wait_for_updates(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> list[AwsShadowUpdate]:
        del timeout_seconds
        await asyncio.Event().wait()
        return []


def registration(thing_name: str) -> ThingRegistration:
    return ThingRegistration(
        thing_name=thing_name,
        thing_type="unit",
        name=thing_name,
        short_id=thing_name,
        town_name="town",
        rig_name="rig",
        capabilities_set=("sparkplug", "mcu", "board", "mcp", "video"),
    )


def online_state(
    thing_name: str,
    *,
    power: bool,
    transport: str = TRANSPORT_BLE_GATT,
    sleep_model: str = SLEEP_MODEL_BLE_RENDEZVOUS,
    native_identity: dict[str, object] | None = None,
) -> ConnectivityState:
    return ConnectivityState(
        adapter_id="adapter",
        thing_name=thing_name,
        transport=transport,
        native_identity=native_identity or {"bleDeviceId": f"ble-{thing_name}"},
        presence=PRESENCE_ONLINE,
        control_availability=CONTROL_EVENTUAL,
        power=power,
        sleep_model=sleep_model,
        battery_mv=3800,
        observed_at_ms=1714380000000,
    )


class DeviceSparkplugMqttSessionTests(unittest.TestCase):
    def test_device_session_configures_ddeath_last_will_and_birth_after_connect(self) -> None:
        instances: list[object] = []

        class FakeConnection:
            def __init__(self, config: object, **kwargs: object) -> None:
                self.config = config
                self.kwargs = kwargs
                self.connect_calls = 0
                self.publishes: list[tuple[str, bytes]] = []
                instances.append(self)

            async def connect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.connect_calls += 1

            async def publish(
                self,
                topic: str,
                payload: bytes,
                *,
                timeout_seconds: float | None = None,
            ) -> None:
                del timeout_seconds
                self.publishes.append((topic, payload))

            async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds

        session = DeviceSparkplugMqttSession(
            SparkplugMqttSessionConfig(
                endpoint="endpoint",
                aws_region="eu-central-1",
                sparkplug_group_id="town",
                sparkplug_edge_node_id="rig",
                client_id="unit-1",
            ),
            thing_name="unit-1",
            aws_runtime=object(),  # type: ignore[arg-type]
            connection_factory=FakeConnection,
        )

        asyncio.run(session.publish_birth(redcon=4, battery_mv=3795))

        connection = instances[0]
        will_topic = getattr(connection.config, "will_topic")
        will_payload = getattr(connection.config, "will_payload")
        self.assertEqual(will_topic, "spBv1.0/town/DDEATH/rig/unit-1")
        self.assertEqual(len(decode_payload(will_payload).metrics), 0)
        self.assertEqual(connection.connect_calls, 1)
        self.assertEqual(connection.publishes[0][0], "spBv1.0/town/DBIRTH/rig/unit-1")
        self.assertIn("on_connection_interrupted", connection.kwargs)

        connection.kwargs["on_connection_interrupted"](RuntimeError("lost"))
        self.assertFalse(session.connected)
        self.assertFalse(session.born)

    def test_device_session_failed_initial_connect_does_not_disconnect_unconnected_connection(
        self,
    ) -> None:
        instances: list[object] = []

        class FailingConnection:
            def __init__(self, config: object, **kwargs: object) -> None:
                self.config = config
                self.kwargs = kwargs
                self.disconnect_calls = 0
                instances.append(self)

            async def connect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                raise RuntimeError("connect rejected")

            async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
                del timeout_seconds
                self.disconnect_calls += 1
                raise AssertionError("disconnect before connect")

        session = DeviceSparkplugMqttSession(
            SparkplugMqttSessionConfig(
                endpoint="endpoint",
                aws_region="eu-central-1",
                sparkplug_group_id="town",
                sparkplug_edge_node_id="rig",
                client_id="unit-1",
            ),
            thing_name="unit-1",
            aws_runtime=object(),  # type: ignore[arg-type]
            connection_factory=FailingConnection,
        )

        with self.assertRaisesRegex(RuntimeError, "connect rejected"):
            asyncio.run(session.publish_birth(redcon=4, battery_mv=3795))
        asyncio.run(session.teardown(explicit_death=False))

        connection = instances[0]
        self.assertEqual(connection.disconnect_calls, 0)
        self.assertFalse(session.connected)
        self.assertFalse(session.born)
        self.assertIn("on_connection_failure", connection.kwargs)


class SparkplugManagerTests(unittest.TestCase):
    def test_parse_args_accepts_pre_resolved_iot_endpoint_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RIG_NAME": "rig-prod",
                "SPARKPLUG_GROUP_ID": "town-prod",
                "SPARKPLUG_EDGE_NODE_ID": "rig-prod",
                "AWS_IOT_ENDPOINT": "abc123-ats.iot.eu-central-1.amazonaws.com",
            },
            clear=True,
        ):
            with patch("sys.argv", ["rig-sparkplug-manager"]):
                args = _parse_args()

        self.assertEqual(args.iot_endpoint, "abc123-ats.iot.eu-central-1.amazonaws.com")

    def test_build_bridge_config_uses_runtime_endpoint(self) -> None:
        with patch("sys.argv", ["rig-sparkplug-manager"]):
            args = _parse_args()

        config = _build_bridge_config(
            args,
            aws_runtime=FakeAwsRuntime(),  # type: ignore[arg-type]
            aws_region="eu-central-1",
        )

        self.assertEqual(config.iot_endpoint, "endpoint")

    def test_device_session_client_id_is_managed_thing_name(self) -> None:
        manager = SparkplugManager(
            BridgeConfig(
                iot_endpoint="endpoint",
                aws_region="eu-central-1",
                rig_name="rig",
            ),
            aws_runtime=object(),  # type: ignore[arg-type]
            bus=InMemoryLocalPubSub(),
            cloud_client=FakeCloudClient(),  # type: ignore[arg-type]
            session_factory=FakeDeviceSession,  # type: ignore[arg-type]
        )

        config = manager._device_session_config("unit-cd5xu6")

        self.assertEqual(config.client_id, "unit-cd5xu6")

    def test_manager_republishes_inventory_for_late_connectivity_adapter(self) -> None:
        async def exercise() -> ConnectivityInventory:
            bus = InMemoryLocalPubSub()
            cloud = FakeLifecycleCloud()
            task = asyncio.create_task(
                run_sparkplug_manager(
                    config=BridgeConfig(
                        iot_endpoint="endpoint",
                        aws_region="eu-central-1",
                        rig_name="rig",
                        sparkplug_group_id="town",
                        sparkplug_edge_node_id="rig",
                    ),
                    aws_runtime=FakeAwsRuntime(),  # type: ignore[arg-type]
                    bus=bus,
                    registry_client=FakeRegistryClient([registration("unit-1")]),  # type: ignore[arg-type]
                    cloud_client=cloud,  # type: ignore[arg-type]
                    inventory_publish_interval=0.01,
                )
            )
            await asyncio.wait_for(cloud.node_birth_published.wait(), timeout=1.0)

            received: asyncio.Queue[bytes] = asyncio.Queue()

            def handler(_topic: str, payload: bytes) -> None:
                received.put_nowait(payload)

            await bus.subscribe(INVENTORY_TOPIC, handler)
            payload = await asyncio.wait_for(received.get(), timeout=1.0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return ConnectivityInventory.from_payload(payload)

        inventory = asyncio.run(exercise())

        self.assertGreaterEqual(inventory.seq, 2)
        self.assertEqual([device.thing_name for device in inventory.devices], ["unit-1"])

    def test_manager_service_publishes_only_node_birth_and_death_for_rig(self) -> None:
        async def exercise() -> FakeLifecycleCloud:
            cloud = FakeLifecycleCloud()
            task = asyncio.create_task(
                run_sparkplug_manager(
                    config=BridgeConfig(
                        iot_endpoint="endpoint",
                        aws_region="eu-central-1",
                        rig_name="rig",
                        sparkplug_group_id="town",
                        sparkplug_edge_node_id="rig",
                    ),
                    aws_runtime=FakeAwsRuntime(),  # type: ignore[arg-type]
                    bus=InMemoryLocalPubSub(),
                    registry_client=FakeRegistryClient([registration("unit-1")]),  # type: ignore[arg-type]
                    cloud_client=cloud,  # type: ignore[arg-type]
                )
            )
            await asyncio.wait_for(cloud.node_birth_published.wait(), timeout=1.0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return cloud

        cloud = asyncio.run(exercise())

        topics = [topic for topic, _payload in cloud.sparkplug_publishes]
        self.assertEqual(
            topics,
            [
                "spBv1.0/town/NBIRTH/rig",
                "spBv1.0/town/NDEATH/rig",
            ],
        )
        self.assertEqual(cloud.events[0], "connect")
        self.assertNotIn("spBv1.0/town/DBIRTH/rig", topics)
        self.assertNotIn("spBv1.0/town/DDEATH/rig", topics)
        self.assertEqual(cloud.disconnect_calls, 1)

    def test_multiple_devices_have_independent_sessions(self) -> None:
        async def exercise() -> tuple[SparkplugManager, FakeCloudClient]:
            bus = InMemoryLocalPubSub()
            cloud = FakeCloudClient()
            manager = SparkplugManager(
                BridgeConfig(
                    iot_endpoint="endpoint",
                    aws_region="eu-central-1",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="rig",
                ),
                aws_runtime=object(),  # type: ignore[arg-type]
                bus=bus,
                cloud_client=cloud,  # type: ignore[arg-type]
                session_factory=FakeDeviceSession,  # type: ignore[arg-type]
            )
            await manager.set_registrations([registration("unit-1"), registration("unit-2")])
            await manager.apply_connectivity_state(online_state("unit-1", power=False))
            await manager.apply_connectivity_state(online_state("unit-2", power=True))
            await manager.apply_connectivity_state(
                ConnectivityState(
                    adapter_id="adapter",
                    thing_name="unit-1",
                    transport=TRANSPORT_BLE_GATT,
                    native_identity={"bleDeviceId": "ble-unit-1"},
                    presence=PRESENCE_OFFLINE,
                    control_availability="unavailable",
                    power=False,
                    sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
                    battery_mv=3800,
                    observed_at_ms=1714380000100,
                )
            )
            return manager, cloud

        manager, cloud = asyncio.run(exercise())

        session_1 = manager.devices["unit-1"].mqtt_session
        session_2 = manager.devices["unit-2"].mqtt_session
        assert isinstance(session_1, FakeDeviceSession)
        assert isinstance(session_2, FakeDeviceSession)
        self.assertEqual(session_1.births, [(4, 3800)])
        self.assertEqual(session_1.deaths, 1)
        self.assertEqual(session_2.births, [(3, 3800)])
        self.assertEqual(session_2.deaths, 0)
        self.assertEqual(
            [update["thing_name"] for update in cloud.named_shadow_updates],
            ["unit-1", "unit-2", "unit-1"],
        )

    def test_device_birth_failure_is_retried_on_next_connectivity_state(self) -> None:
        async def exercise() -> FailingBirthOnceDeviceSession:
            manager = SparkplugManager(
                BridgeConfig(iot_endpoint="endpoint", aws_region="eu-central-1"),
                aws_runtime=object(),  # type: ignore[arg-type]
                bus=InMemoryLocalPubSub(),
                cloud_client=FakeCloudClient(),  # type: ignore[arg-type]
                session_factory=FailingBirthOnceDeviceSession,  # type: ignore[arg-type]
            )
            await manager.set_registrations([registration("unit-1")])
            await manager.apply_connectivity_state(online_state("unit-1", power=True))
            session = manager.devices["unit-1"].mqtt_session
            assert isinstance(session, FailingBirthOnceDeviceSession)
            self.assertFalse(session.born)
            self.assertEqual(session.disconnects, 1)
            self.assertEqual(session.deaths, 0)

            await manager.apply_connectivity_state(online_state("unit-1", power=True))
            return session

        session = asyncio.run(exercise())
        self.assertEqual(session.births, [(3, 3800)])
        self.assertTrue(session.connected)
        self.assertTrue(session.born)
        self.assertEqual(session.disconnects, 1)
        self.assertEqual(session.deaths, 0)

    def test_redcon_four_reachable_sleep_state_remains_born(self) -> None:
        async def exercise() -> FakeDeviceSession:
            manager = SparkplugManager(
                BridgeConfig(iot_endpoint="endpoint", aws_region="eu-central-1"),
                aws_runtime=object(),  # type: ignore[arg-type]
                bus=InMemoryLocalPubSub(),
                cloud_client=FakeCloudClient(),  # type: ignore[arg-type]
                session_factory=FakeDeviceSession,  # type: ignore[arg-type]
            )
            await manager.set_registrations([registration("unit-1")])
            await manager.apply_connectivity_state(online_state("unit-1", power=False))
            session = manager.devices["unit-1"].mqtt_session
            assert isinstance(session, FakeDeviceSession)
            return session

        session = asyncio.run(exercise())
        self.assertEqual(session.births, [(4, 3800)])
        self.assertEqual(session.deaths, 0)
        self.assertTrue(session.born)

    def test_matter_icd_state_uses_same_manager_path(self) -> None:
        async def exercise() -> ManagedDeviceState:
            manager = SparkplugManager(
                BridgeConfig(iot_endpoint="endpoint", aws_region="eu-central-1"),
                aws_runtime=object(),  # type: ignore[arg-type]
                bus=InMemoryLocalPubSub(),
                cloud_client=FakeCloudClient(),  # type: ignore[arg-type]
                session_factory=FakeDeviceSession,  # type: ignore[arg-type]
            )
            await manager.set_registrations([registration("unit-matter")])
            await manager.apply_connectivity_state(
                online_state(
                    "unit-matter",
                    power=False,
                    transport=TRANSPORT_MATTER,
                    sleep_model=SLEEP_MODEL_MATTER_ICD,
                    native_identity={"matterNodeId": 57, "fabricId": "fabric-1"},
                )
            )
            return manager.devices["unit-matter"]

        device = asyncio.run(exercise())
        self.assertEqual(device.redcon, 4)
        self.assertTrue(device.reachable())
        assert isinstance(device.mqtt_session, FakeDeviceSession)
        self.assertTrue(device.mqtt_session.born)

    def test_dcmd_redcon_publishes_connectivity_command(self) -> None:
        async def exercise() -> list[bytes]:
            bus = InMemoryLocalPubSub()
            manager = SparkplugManager(
                BridgeConfig(iot_endpoint="endpoint", aws_region="eu-central-1"),
                aws_runtime=object(),  # type: ignore[arg-type]
                bus=bus,
                cloud_client=FakeCloudClient(),  # type: ignore[arg-type]
                session_factory=FakeDeviceSession,  # type: ignore[arg-type]
            )
            received: list[bytes] = []

            def handler(_topic: str, payload: bytes) -> None:
                received.append(payload)

            await bus.subscribe("dev/txing/rig/v1/connectivity/command/unit-1", handler)
            await manager.set_registrations([registration("unit-1")])
            await manager.apply_cloud_updates(
                [
                    AwsShadowUpdate(
                        thing_name="unit-1",
                        source="sparkplug/dcmd",
                        command_redcon=3,
                    )
                ]
            )
            return received

        received = asyncio.run(exercise())
        self.assertEqual(len(received), 1)
        self.assertTrue(b'"power":true' in received[0])
        self.assertTrue(b'"reason":"redcon=3"' in received[0])


if __name__ == "__main__":
    unittest.main()
