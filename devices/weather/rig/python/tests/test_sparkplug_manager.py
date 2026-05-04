from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from rig.connectivity_protocol import (
    COMMAND_FAILED,
    CONTROL_EVENTUAL,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
    WeatherMeasurements,
    build_command_result_topic,
    build_command_topic,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import (
    build_device_death_payload,
    build_device_topic,
    build_redcon_payload,
    decode_payload,
)
from rig.thing_registry import ThingRegistration
from weather_rig.sparkplug_manager import (
    WeatherSparkplugConfig,
    WeatherSparkplugManager,
)


class FakeConnection:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def connect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        del timeout_seconds
        self.published.append((topic, payload))

    async def subscribe(
        self,
        topic: str,
        callback: object,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        del topic, callback, timeout_seconds

    async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds


class FakeDeviceSession:
    instances: list["FakeDeviceSession"] = []

    def __init__(
        self,
        config: object,
        *,
        thing_name: str,
        aws_runtime: object,
        **_kwargs: object,
    ) -> None:
        del aws_runtime
        self.config = config
        self.thing_name = thing_name
        self.connected = False
        self.born = False
        self.published: list[tuple[str, bytes]] = []
        self._seq = 0
        FakeDeviceSession.instances.append(self)

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    async def publish_birth_payload(self, payload_factory: object) -> None:
        if self.connected and self.born:
            return
        self.connected = True
        self.born = True
        topic = build_device_topic(
            self.config.sparkplug_group_id,
            "DBIRTH",
            self.config.sparkplug_edge_node_id,
            self.thing_name,
        )
        self.published.append((topic, payload_factory(self._next_seq())))

    async def publish_data_payload(self, payload_factory: object) -> bool:
        if not self.connected or not self.born:
            return False
        topic = build_device_topic(
            self.config.sparkplug_group_id,
            "DDATA",
            self.config.sparkplug_edge_node_id,
            self.thing_name,
        )
        self.published.append((topic, payload_factory(self._next_seq())))
        return True

    async def teardown(self, *, explicit_death: bool) -> None:
        if explicit_death:
            topic = build_device_topic(
                self.config.sparkplug_group_id,
                "DDEATH",
                self.config.sparkplug_edge_node_id,
                self.thing_name,
            )
            self.published.append((topic, build_device_death_payload(seq=self._next_seq())))
        self.connected = False
        self.born = False


def registration(thing_name: str) -> ThingRegistration:
    return ThingRegistration(
        thing_name=thing_name,
        thing_type="weather",
        name="outside",
        short_id=thing_name,
        town_name="town",
        rig_name="server",
        capabilities_set=("sparkplug",),
    )


def weather_state() -> ConnectivityState:
    return ConnectivityState(
        adapter_id="weather-ble-main",
        thing_name="weather-1",
        transport=TRANSPORT_BLE_GATT,
        native_identity={"bleLocalName": "weather-1"},
        presence=PRESENCE_ONLINE,
        control_availability=CONTROL_EVENTUAL,
        power=False,
        sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
        battery_mv=3512,
        observed_at_ms=1714380000000,
        weather=WeatherMeasurements(
            measured_temperature=21.625,
            measured_pressure=100.8,
            measured_humidity=44.5,
        ),
    )


class WeatherSparkplugManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDeviceSession.instances = []

    def test_birth_payload_includes_redcon_four_and_weather_metrics(self) -> None:
        async def exercise() -> tuple[FakeDeviceSession, str, bytes]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(weather_state())
            session = FakeDeviceSession.instances[0]
            topic, payload = session.published[0]
            return session, topic, payload

        session, topic, payload = asyncio.run(exercise())

        self.assertEqual(session.config.client_id, "weather-1")
        self.assertEqual(topic, "spBv1.0/town/DBIRTH/server/weather-1")
        decoded = decode_payload(payload)
        metrics = {metric.name: metric for metric in decoded.metrics}
        self.assertEqual(metrics["redcon"].int_value, 4)
        self.assertEqual(metrics["batteryMv"].int_value, 3512)
        self.assertEqual(metrics["measuredTemperature"].double_value, 21.625)
        self.assertEqual(metrics["measuredPressure"].double_value, 100.8)
        self.assertEqual(metrics["measuredHumidity"].double_value, 44.5)

    def test_active_payload_reports_redcon_three_and_weather_metrics(self) -> None:
        async def exercise() -> tuple[str, bytes]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(
                ConnectivityState(
                    adapter_id="weather-ble-main",
                    thing_name="weather-1",
                    transport=TRANSPORT_BLE_GATT,
                    native_identity={"bleLocalName": "weather-1"},
                    presence=PRESENCE_ONLINE,
                    control_availability=CONTROL_EVENTUAL,
                    power=True,
                    sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
                    battery_mv=3500,
                    observed_at_ms=1714380000000,
                    weather=WeatherMeasurements(
                        measured_temperature=22.0,
                        measured_pressure=101.3,
                        measured_humidity=45.0,
                    ),
                )
            )
            return FakeDeviceSession.instances[0].published[0]

        topic, payload = asyncio.run(exercise())

        self.assertEqual(topic, "spBv1.0/town/DBIRTH/server/weather-1")
        decoded = decode_payload(payload)
        metrics = {metric.name: metric for metric in decoded.metrics}
        self.assertEqual(metrics["redcon"].int_value, 3)
        self.assertEqual(metrics["batteryMv"].int_value, 3500)
        self.assertEqual(metrics["measuredTemperature"].double_value, 22.0)

    def test_offline_after_birth_publishes_death(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(weather_state())
            await manager.apply_connectivity_state(
                ConnectivityState(
                    adapter_id="weather-ble-main",
                    thing_name="weather-1",
                    transport=TRANSPORT_BLE_GATT,
                    native_identity={"bleLocalName": "weather-1"},
                    presence=PRESENCE_OFFLINE,
                    control_availability="unavailable",
                    power=False,
                    sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
                    battery_mv=None,
                    observed_at_ms=1714380001000,
                    weather=None,
                )
            )
            return FakeDeviceSession.instances[0].published

        published = asyncio.run(exercise())

        self.assertEqual(published[0][0], "spBv1.0/town/DBIRTH/server/weather-1")
        self.assertEqual(published[1][0], "spBv1.0/town/DDEATH/server/weather-1")

    def test_unchanged_online_refresh_does_not_publish_ddata(self) -> None:
        async def exercise() -> tuple[list[tuple[str, bytes]], int, bool]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            state = weather_state()
            refreshed_state = replace(
                state,
                observed_at_ms=state.observed_at_ms + 30_000,
                seq=state.seq + 1,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(state)
            await manager.apply_connectivity_state(refreshed_state)
            device = manager.devices["weather-1"]
            return FakeDeviceSession.instances[0].published, device.last_reported_at_ms, device.born

        published, last_reported_at_ms, born = asyncio.run(exercise())

        self.assertEqual(
            [topic for topic, _payload in published],
            ["spBv1.0/town/DBIRTH/server/weather-1"],
        )
        self.assertEqual(last_reported_at_ms, 1714380030000)
        self.assertTrue(born)

    def test_changed_weather_state_publishes_ddata(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            state = weather_state()
            changed_state = replace(
                state,
                battery_mv=3513,
                observed_at_ms=state.observed_at_ms + 30_000,
                seq=state.seq + 1,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(state)
            await manager.apply_connectivity_state(changed_state)
            return FakeDeviceSession.instances[0].published

        published = asyncio.run(exercise())

        self.assertEqual(
            [topic for topic, _payload in published],
            [
                "spBv1.0/town/DBIRTH/server/weather-1",
                "spBv1.0/town/DDATA/server/weather-1",
            ],
        )
        ddata = decode_payload(published[1][1])
        metrics = {metric.name: metric for metric in ddata.metrics}
        self.assertEqual(metrics["batteryMv"].int_value, 3513)

    def test_ignores_non_weather_registrations(self) -> None:
        async def exercise() -> list[str]:
            bus = InMemoryLocalPubSub()
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await manager.set_registrations(
                [
                    registration("weather-1"),
                    ThingRegistration(
                        thing_name="unit-1",
                        thing_type="unit",
                        name="bot",
                        short_id="unit-1",
                        town_name="town",
                        rig_name="server",
                        capabilities_set=("sparkplug",),
                    ),
                ]
            )
            return list(manager.devices)

        self.assertEqual(asyncio.run(exercise()), ["weather-1"])

    def test_publishes_ble_connected_idle_inventory(self) -> None:
        async def exercise() -> ConnectivityInventory:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(
                INVENTORY_TOPIC,
                lambda _topic, payload: published.append(payload),
            )
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await manager.set_registrations([registration("weather-1")])
            return ConnectivityInventory.from_payload(published[-1])

        inventory = asyncio.run(exercise())

        self.assertEqual([device.thing_name for device in inventory.devices], ["weather-1"])
        self.assertEqual(inventory.devices[0].transport, TRANSPORT_BLE_GATT)
        self.assertEqual(inventory.devices[0].sleep_model, SLEEP_MODEL_BLE_CONNECTED_IDLE)

    def test_dcmd_redcon_three_publishes_local_ble_command(self) -> None:
        async def exercise(redcon: int) -> ConnectivityCommand:
            bus = InMemoryLocalPubSub()
            commands: list[bytes] = []
            await bus.subscribe(
                build_command_topic("weather-1"),
                lambda _topic, payload: commands.append(payload),
            )
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager._handle_dcmd_message(
                build_device_topic("town", "DCMD", "server", "weather-1"),
                build_redcon_payload(redcon=redcon, seq=9),
            )
            return ConnectivityCommand.from_payload(commands[0])

        command = asyncio.run(exercise(3))

        self.assertTrue(command.power)
        self.assertEqual(command.reason, "redcon=3")
        self.assertEqual(command.seq, 9)

        command = asyncio.run(exercise(2))

        self.assertTrue(command.power)
        self.assertEqual(command.reason, "redcon=2")

    def test_dcmd_redcon_four_publishes_idle_command(self) -> None:
        async def exercise() -> ConnectivityCommand:
            bus = InMemoryLocalPubSub()
            commands: list[bytes] = []
            await bus.subscribe(
                build_command_topic("weather-1"),
                lambda _topic, payload: commands.append(payload),
            )
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager._handle_dcmd_message(
                build_device_topic("town", "DCMD", "server", "weather-1"),
                build_redcon_payload(redcon=4, seq=10),
            )
            return ConnectivityCommand.from_payload(commands[0])

        command = asyncio.run(exercise())

        self.assertFalse(command.power)
        self.assertEqual(command.reason, "redcon=4")
        self.assertEqual(command.seq, 10)

    def test_command_result_failure_publishes_sparkplug_ddata_status(self) -> None:
        async def exercise() -> tuple[list[tuple[str, bytes]], ConnectivityCommand]:
            bus = InMemoryLocalPubSub()
            commands: list[ConnectivityCommand] = []
            await bus.subscribe(
                build_command_topic("weather-1"),
                lambda _topic, payload: commands.append(ConnectivityCommand.from_payload(payload)),
            )
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(weather_state())
            await manager._handle_dcmd_message(
                build_device_topic("town", "DCMD", "server", "weather-1"),
                build_redcon_payload(redcon=3, seq=12),
            )
            command = commands[0]
            await manager.apply_connectivity_command_result(
                ConnectivityCommandResult(
                    adapter_id="weather-ble-main",
                    command_id=command.command_id,
                    thing_name="weather-1",
                    status=COMMAND_FAILED,
                    message="weather BLE command deadline expired",
                    observed_at_ms=1714380045000,
                    seq=command.seq,
                )
            )
            return FakeDeviceSession.instances[0].published, command

        published, command = asyncio.run(exercise())

        self.assertEqual(
            [topic for topic, _payload in published],
            [
                "spBv1.0/town/DBIRTH/server/weather-1",
                "spBv1.0/town/DDATA/server/weather-1",
            ],
        )
        ddata = decode_payload(published[1][1])
        metrics = {metric.name: metric for metric in ddata.metrics}
        self.assertEqual(metrics["redcon"].int_value, 4)
        self.assertEqual(metrics["redconCommandStatus"].string_value, COMMAND_FAILED)
        self.assertEqual(metrics["redconCommandSeq"].int_value, 12)
        self.assertEqual(metrics["redconCommandTarget"].int_value, 3)
        self.assertEqual(metrics["redconCommandMessage"].string_value, "weather BLE command deadline expired")
        self.assertEqual(metrics["redconCommandId"].string_value, command.command_id)

    def test_command_result_subscription_publishes_sparkplug_ddata_status(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            commands: list[ConnectivityCommand] = []
            await bus.subscribe(
                build_command_topic("weather-1"),
                lambda _topic, payload: commands.append(ConnectivityCommand.from_payload(payload)),
            )
            manager = WeatherSparkplugManager(
                WeatherSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.start()
            await manager.apply_connectivity_state(weather_state())
            await manager._handle_dcmd_message(
                build_device_topic("town", "DCMD", "server", "weather-1"),
                build_redcon_payload(redcon=3, seq=13),
            )
            command = commands[0]
            await bus.publish(
                build_command_result_topic("weather-1"),
                ConnectivityCommandResult(
                    adapter_id="weather-ble-main",
                    command_id=command.command_id,
                    thing_name="weather-1",
                    status=COMMAND_FAILED,
                    message="failed to discover services",
                    observed_at_ms=1714380045000,
                    seq=command.seq,
                ).to_json(),
            )
            return FakeDeviceSession.instances[0].published

        published = asyncio.run(exercise())

        self.assertEqual(published[-1][0], "spBv1.0/town/DDATA/server/weather-1")
        metrics = {metric.name: metric for metric in decode_payload(published[-1][1]).metrics}
        self.assertEqual(metrics["redconCommandSeq"].int_value, 13)
        self.assertEqual(metrics["redconCommandMessage"].string_value, "failed to discover services")


if __name__ == "__main__":
    unittest.main()
