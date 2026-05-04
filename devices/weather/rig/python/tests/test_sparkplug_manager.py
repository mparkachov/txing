from __future__ import annotations

import asyncio
import unittest

from rig.connectivity_protocol import (
    CONTROL_EVENTUAL,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    ConnectivityCommand,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
    WeatherMeasurements,
    build_command_topic,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import build_device_topic, build_redcon_payload, decode_payload
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
    def test_birth_payload_includes_redcon_four_and_weather_metrics(self) -> None:
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
            )
            await manager.set_registrations([registration("weather-1")])
            await manager.connect()
            await manager.apply_connectivity_state(weather_state())
            assert manager._connection is not None
            return manager._connection.published[0]  # type: ignore[union-attr]

        topic, payload = asyncio.run(exercise())

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
            assert manager._connection is not None
            return manager._connection.published[0]  # type: ignore[union-attr]

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
            assert manager._connection is not None
            return manager._connection.published  # type: ignore[union-attr]

        published = asyncio.run(exercise())

        self.assertEqual(published[0][0], "spBv1.0/town/DBIRTH/server/weather-1")
        self.assertEqual(published[1][0], "spBv1.0/town/DDEATH/server/weather-1")

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


if __name__ == "__main__":
    unittest.main()
