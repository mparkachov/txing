from __future__ import annotations

import asyncio
import json
import unittest

from rig.connectivity_protocol import ConnectivityState, build_state_topic
from rig.local_pubsub import InMemoryLocalPubSub
from weather_rig.matter_watch import (
    WeatherMatterWatchConfig,
    publish_watcher_line,
    state_from_watcher_payload,
)


class WeatherMatterWatchTests(unittest.TestCase):
    def test_watcher_payload_maps_to_connectivity_weather_state(self) -> None:
        state = state_from_watcher_payload(
            {
                "status": "online",
                "observedAtMs": 1714380000000,
                "batteryMv": 3512,
                "measuredTemperature": 21.625,
                "measuredPressure": 100.8,
                "measuredHumidity": 44.5,
            },
            config=WeatherMatterWatchConfig(
                thing_name="weather-1",
                matter_node_id="0x1234",
            ),
            seq=7,
        )

        self.assertEqual(state.thing_name, "weather-1")
        self.assertEqual(state.transport, "matter")
        self.assertEqual(state.presence, "online")
        self.assertEqual(state.control_availability, "unavailable")
        self.assertEqual(state.battery_mv, 3512)
        assert state.weather is not None
        self.assertEqual(state.weather.measured_temperature, 21.625)
        self.assertEqual(state.weather.measured_pressure, 100.8)
        self.assertEqual(state.weather.measured_humidity, 44.5)

    def test_publish_watcher_line_sends_local_state(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            states: list[ConnectivityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(ConnectivityState.from_payload(payload))

            await bus.subscribe(build_state_topic("weather-1"), state_handler)
            await publish_watcher_line(
                json.dumps(
                    {
                        "status": "online",
                        "batteryMv": 3512,
                        "measuredTemperature": 21.625,
                    }
                ),
                config=WeatherMatterWatchConfig(
                    thing_name="weather-1",
                    matter_node_id="0x1234",
                ),
                bus=bus,
                seq=1,
            )
            return states[0]

        state = asyncio.run(exercise())

        self.assertEqual(state.thing_name, "weather-1")
        self.assertEqual(state.battery_mv, 3512)


if __name__ == "__main__":
    unittest.main()
