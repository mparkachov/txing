from __future__ import annotations

import asyncio
import unittest

from rig.device_sparkplug_session import (
    DeviceSparkplugMqttSession,
    SparkplugMqttSessionConfig,
)
from rig.sparkplug import decode_payload


class FakeConnection:
    instances: list["FakeConnection"] = []

    def __init__(self, config: object, **_kwargs: object) -> None:
        self.config = config
        self.connected = False
        self.disconnected = False
        self.published: list[tuple[str, bytes]] = []
        FakeConnection.instances.append(self)

    async def connect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds
        self.connected = True

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
        self.disconnected = True


class DeviceSparkplugMqttSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeConnection.instances = []

    def test_uses_thing_name_client_id_and_will_death(self) -> None:
        async def exercise() -> FakeConnection:
            session = DeviceSparkplugMqttSession(
                SparkplugMqttSessionConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                    client_id="weather-1",
                ),
                thing_name="weather-1",
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await session.publish_birth(redcon=4, battery_mv=3300)
            await session.teardown(explicit_death=True)
            return FakeConnection.instances[0]

        connection = asyncio.run(exercise())

        self.assertEqual(connection.config.client_id, "weather-1")
        self.assertEqual(connection.config.will_topic, "spBv1.0/town/DDEATH/server/weather-1")
        self.assertTrue(connection.disconnected)
        self.assertEqual(
            [topic for topic, _payload in connection.published],
            [
                "spBv1.0/town/DBIRTH/server/weather-1",
                "spBv1.0/town/DDEATH/server/weather-1",
            ],
        )
        birth = decode_payload(connection.published[0][1])
        metrics = {metric.name: metric for metric in birth.metrics}
        self.assertEqual(metrics["redcon"].int_value, 4)
        self.assertEqual(metrics["batteryMv"].int_value, 3300)


if __name__ == "__main__":
    unittest.main()
