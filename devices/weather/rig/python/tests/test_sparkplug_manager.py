from __future__ import annotations

import asyncio
import unittest

from rig.connectivity_protocol import (
    CONTROL_UNAVAILABLE,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    ConnectivityState,
    WeatherMeasurements,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import decode_payload
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
        adapter_id="weather-matter-watch",
        thing_name="weather-1",
        transport="matter",
        native_identity={"matterNodeId": "0x1234"},
        presence=PRESENCE_ONLINE,
        control_availability=CONTROL_UNAVAILABLE,
        power=None,
        sleep_model="matter-icd",
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

    def test_offline_payload_omits_missing_battery_and_weather_metrics(self) -> None:
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
                    adapter_id="weather-matter-watch",
                    thing_name="weather-1",
                    transport="matter",
                    native_identity={"matterNodeId": "0x1234"},
                    presence=PRESENCE_OFFLINE,
                    control_availability=CONTROL_UNAVAILABLE,
                    power=None,
                    sleep_model="matter-icd",
                    battery_mv=None,
                    observed_at_ms=1714380000000,
                    weather=None,
                )
            )
            assert manager._connection is not None
            return manager._connection.published[0]  # type: ignore[union-attr]

        topic, payload = asyncio.run(exercise())

        self.assertEqual(topic, "spBv1.0/town/DBIRTH/server/weather-1")
        decoded = decode_payload(payload)
        metrics = {metric.name: metric for metric in decoded.metrics}
        self.assertEqual(metrics["redcon"].int_value, 4)
        self.assertNotIn("batteryMv", metrics)
        self.assertNotIn("measuredTemperature", metrics)
        self.assertNotIn("measuredPressure", metrics)
        self.assertNotIn("measuredHumidity", metrics)

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

    def test_does_not_publish_connectivity_inventory(self) -> None:
        async def exercise() -> list[bytes]:
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
            await manager.start()
            return published

        self.assertEqual(asyncio.run(exercise()), [])


if __name__ == "__main__":
    unittest.main()
