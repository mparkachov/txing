from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from rig.connectivity_protocol import (
    CONTROL_EVENTUAL,
    CONTROL_IMMEDIATE,
    CONTROL_UNAVAILABLE,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    ConnectivityCommand,
    ConnectivityState,
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
from time_rig.sparkplug_manager import (
    TimeSparkplugConfig,
    TimeSparkplugManager,
    redcon_from_connectivity_state,
)


class FakeConnection:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.subscriptions: list[str] = []

    async def connect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds

    async def subscribe(
        self,
        topic: str,
        callback: object,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        del callback, timeout_seconds
        self.subscriptions.append(topic)

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
        thing_type="time",
        name=thing_name,
        short_id=thing_name,
        town_name="town",
        rig_name="aws",
        capabilities_set=("sparkplug", "mcp", "time"),
    )


def connectivity_state(
    *,
    thing_name: str = "clock",
    power: bool | None = False,
    control_availability: str = CONTROL_EVENTUAL,
    presence: str = PRESENCE_ONLINE,
    current_time_iso: str = "2024-04-29T07:20:00Z",
    observed_at_ms: int = 1714380000000,
) -> ConnectivityState:
    return ConnectivityState(
        adapter_id="time-aws",
        thing_name=thing_name,
        transport="matter",
        native_identity={
            "currentTimeIso": current_time_iso,
            "mcpAvailable": control_availability == CONTROL_IMMEDIATE,
        },
        presence=presence,
        control_availability=control_availability,
        power=power,
        sleep_model="matter-icd",
        battery_mv=None,
        observed_at_ms=observed_at_ms,
    )


class TimeSparkplugManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDeviceSession.instances = []

    def test_redcon_mapping_matches_time_connectivity_states(self) -> None:
        self.assertEqual(redcon_from_connectivity_state(connectivity_state(power=False)), 4)
        self.assertEqual(
            redcon_from_connectivity_state(
                connectivity_state(power=True, control_availability=CONTROL_EVENTUAL)
            ),
            3,
        )
        self.assertEqual(
            redcon_from_connectivity_state(
                connectivity_state(power=True, control_availability=CONTROL_IMMEDIATE)
            ),
            1,
        )
        self.assertEqual(
            redcon_from_connectivity_state(
                connectivity_state(
                    power=True,
                    control_availability=CONTROL_UNAVAILABLE,
                    presence=PRESENCE_OFFLINE,
                )
            ),
            4,
        )

    def test_birth_payload_includes_redcon_and_current_time_metric(self) -> None:
        async def exercise() -> tuple[FakeDeviceSession, str, bytes]:
            bus = InMemoryLocalPubSub()
            manager = TimeSparkplugManager(
                TimeSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="aws",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="aws",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("clock")])
            await manager.connect()
            await manager.apply_connectivity_state(
                connectivity_state(power=True, control_availability=CONTROL_IMMEDIATE)
            )
            session = FakeDeviceSession.instances[0]
            topic, payload = session.published[0]
            return session, topic, payload

        session, topic, payload = asyncio.run(exercise())

        self.assertEqual(session.config.client_id, "clock")
        self.assertEqual(topic, "spBv1.0/town/DBIRTH/aws/clock")
        decoded = decode_payload(payload)
        metrics = {metric.name: metric for metric in decoded.metrics}
        self.assertEqual(metrics["redcon"].int_value, 1)
        self.assertEqual(metrics["currentTimeIso"].string_value, "2024-04-29T07:20:00Z")

    def test_stale_device_publishes_ddeath(self) -> None:
        async def exercise() -> list[str]:
            bus = InMemoryLocalPubSub()
            manager = TimeSparkplugManager(
                TimeSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="aws",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="aws",
                    stale_after_ms=10_000,
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("clock")])
            await manager.connect()
            await manager.apply_connectivity_state(
                connectivity_state(observed_at_ms=1714380000000)
            )
            await manager.check_stale_devices(now_ms=1714380010001)
            return [topic for topic, _payload in FakeDeviceSession.instances[0].published]

        topics = asyncio.run(exercise())

        self.assertEqual(topics[-1], "spBv1.0/town/DDEATH/aws/clock")

    def test_dcmd_redcon_publishes_local_connectivity_command(self) -> None:
        async def exercise() -> ConnectivityCommand:
            bus = InMemoryLocalPubSub()
            commands: list[ConnectivityCommand] = []

            async def command_handler(_topic: str, payload: bytes) -> None:
                commands.append(ConnectivityCommand.from_payload(payload))

            await bus.subscribe(build_command_topic("clock"), command_handler)
            manager = TimeSparkplugManager(
                TimeSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="aws",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="aws",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("clock")])
            await manager.connect()
            await manager.handle_mqtt_message(
                "spBv1.0/town/DCMD/aws/clock",
                build_redcon_payload(redcon=1, seq=2, timestamp=1714380000000),
            )
            return commands[0]

        command = asyncio.run(exercise())

        self.assertEqual(command.thing_name, "clock")
        self.assertTrue(command.power)
        self.assertEqual(command.reason, "redcon=1")

    def test_component_entrypoint_retries_startup_failures(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "time_rig"
            / "sparkplug_manager.py"
        ).read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--reconnect-delay"', source)
        self.assertIn("while not shutdown_event.is_set():", source)
        self.assertIn("Time Sparkplug manager failed; retrying", source)
        loop_start = source.index("while not shutdown_event.is_set():")
        runtime_start = source.index("aws_runtime = build_aws_runtime", loop_start)
        self.assertLess(loop_start, runtime_start)


if __name__ == "__main__":
    unittest.main()
