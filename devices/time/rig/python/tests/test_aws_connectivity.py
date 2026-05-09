from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from rig.capability_protocol import (
    CapabilityCommand,
    CapabilityCommandResult,
    CapabilityHeartbeat,
    CapabilityState,
    build_capability_command_result_topic,
    build_capability_command_topic,
    build_capability_heartbeat_topic,
    build_capability_state_topic,
)
from rig.connectivity_protocol import ConnectivityCommandResult as LegacyConnectivityCommandResult
from rig.local_pubsub import InMemoryLocalPubSub
from time_rig.aws_connectivity import TimeAwsConnectivityBridge, TimeAwsConnectivityConfig
from time_rig.time_topics import (
    TIME_MODE_ACTIVE,
    TimeDeviceState,
    build_time_command_result_topic,
    build_time_command_topic,
    build_time_state_topic,
)


class FakeConnection:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.published: list[dict[str, object]] = []
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
        payload: object,
        *,
        retain: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        del timeout_seconds
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "retain": retain,
            }
        )

    async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds


class TimeAwsConnectivityBridgeTests(unittest.TestCase):
    def test_local_command_publishes_retained_time_command(self) -> None:
        async def exercise() -> dict[str, object]:
            bus = InMemoryLocalPubSub()
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            try:
                await bridge.start()
                command = CapabilityCommand(
                    command_id="cmd-1",
                    thing_name="clock",
                    redcon=1,
                    reason="redcon=1",
                    issued_at_ms=1714380000000,
                    deadline_ms=1714380060000,
                )
                await bus.publish(build_capability_command_topic("clock"), command.to_json())
                assert bridge._connection is not None
                return bridge._connection.published[0]  # type: ignore[union-attr]
            finally:
                await bridge.close()

        published = asyncio.run(exercise())

        self.assertEqual(published["topic"], build_time_command_topic("clock"))
        self.assertTrue(published["retain"])
        payload = json.loads(published["payload"])
        self.assertEqual(payload["commandId"], "cmd-1")
        self.assertTrue(payload["target"]["power"])

    def test_start_publishes_v2_heartbeat(self) -> None:
        async def exercise() -> CapabilityHeartbeat:
            bus = InMemoryLocalPubSub()
            heartbeats: list[CapabilityHeartbeat] = []
            heartbeat_seen = asyncio.Event()

            async def heartbeat_handler(_topic: str, payload: bytes) -> None:
                heartbeats.append(CapabilityHeartbeat.from_payload(payload))
                heartbeat_seen.set()

            await bus.subscribe(
                build_capability_heartbeat_topic("time-aws"),
                heartbeat_handler,
            )
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    heartbeat_interval=60.0,
                ),
                bus=bus,
                connection_factory=FakeConnection,
            )
            try:
                await bridge.start()
                await asyncio.wait_for(heartbeat_seen.wait(), timeout=1.0)
                return heartbeats[0]
            finally:
                await bridge.close()

        heartbeat = asyncio.run(exercise())

        self.assertEqual(heartbeat.adapter_id, "time-aws")
        self.assertEqual(heartbeat.status, "running")
        self.assertEqual(heartbeat.seq, 1)

    def test_retained_time_state_maps_to_local_matter_connectivity_state(self) -> None:
        async def exercise() -> CapabilityState:
            bus = InMemoryLocalPubSub()
            states: list[CapabilityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(CapabilityState.from_payload(payload))

            await bus.subscribe(build_capability_state_topic("clock", "time-aws"), state_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            time_state = TimeDeviceState(
                thing_name="clock",
                current_time_iso="2024-04-29T07:20:00Z",
                mode=TIME_MODE_ACTIVE,
                active_until_ms=4102444800000,
                last_command_id="cmd-1",
                observed_at_ms=1714380000000,
                mcp_available=True,
            )
            await bridge.handle_mqtt_message(build_time_state_topic("clock"), time_state.to_json().encode())
            return states[0]

        state = asyncio.run(exercise())

        self.assertEqual(state.thing_name, "clock")
        self.assertEqual(
            state.capabilities,
            {"sparkplug": True, "time": True, "mcp": True},
        )
        self.assertEqual(state.metrics["currentTimeIso"].value, "2024-04-29T07:20:00Z")

    def test_heartbeat_refreshes_latest_capability_state(self) -> None:
        async def exercise() -> list[CapabilityState]:
            bus = InMemoryLocalPubSub()
            states: list[CapabilityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(CapabilityState.from_payload(payload))

            await bus.subscribe(build_capability_state_topic("clock", "time-aws"), state_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            time_state = TimeDeviceState(
                thing_name="clock",
                current_time_iso="2024-04-29T07:20:00Z",
                mode=TIME_MODE_ACTIVE,
                active_until_ms=4102444800000,
                last_command_id="cmd-1",
                observed_at_ms=1714380000000,
                mcp_available=True,
            )
            await bridge.publish_connectivity_state(time_state)
            await bridge._publish_heartbeat(7)
            return states

        states = asyncio.run(exercise())

        self.assertEqual(len(states), 2)
        self.assertEqual(states[0].observed_at_ms, 1714380000000)
        self.assertGreater(states[1].observed_at_ms, states[0].observed_at_ms)
        self.assertEqual(states[1].capabilities, states[0].capabilities)

    def test_heartbeat_projects_expired_active_state_to_sleep(self) -> None:
        async def exercise() -> CapabilityState:
            bus = InMemoryLocalPubSub()
            states: list[CapabilityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(CapabilityState.from_payload(payload))

            await bus.subscribe(build_capability_state_topic("clock", "time-aws"), state_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            time_state = TimeDeviceState(
                thing_name="clock",
                current_time_iso="2024-04-29T07:20:00Z",
                mode=TIME_MODE_ACTIVE,
                active_until_ms=1714380300000,
                last_command_id="cmd-1",
                observed_at_ms=1714380000000,
                mcp_available=True,
            )
            await bridge.publish_connectivity_state(time_state)
            with patch("time_rig.aws_connectivity.utc_timestamp_ms", return_value=1714380300001):
                await bridge._publish_heartbeat(7)
            return states[-1]

        state = asyncio.run(exercise())

        self.assertEqual(state.capabilities, {"sparkplug": True, "time": False, "mcp": False})
        self.assertEqual(state.metrics["mode"].value, "sleep")
        self.assertEqual(state.metrics["activeUntilMs"].value, 0)

    def test_expired_retained_time_state_maps_to_sleep_immediately(self) -> None:
        async def exercise() -> CapabilityState:
            bus = InMemoryLocalPubSub()
            states: list[CapabilityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(CapabilityState.from_payload(payload))

            await bus.subscribe(build_capability_state_topic("clock", "time-aws"), state_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            time_state = TimeDeviceState(
                thing_name="clock",
                current_time_iso="2024-04-29T07:20:00Z",
                mode=TIME_MODE_ACTIVE,
                active_until_ms=1714380300000,
                last_command_id="cmd-1",
                observed_at_ms=1714380000000,
                mcp_available=True,
            )
            with patch("time_rig.aws_connectivity.utc_timestamp_ms", return_value=1714380300001):
                await bridge.handle_mqtt_message(
                    build_time_state_topic("clock"),
                    time_state.to_json().encode(),
                )
            return states[0]

        state = asyncio.run(exercise())

        self.assertEqual(state.capabilities, {"sparkplug": True, "time": False, "mcp": False})
        self.assertEqual(state.metrics["mode"].value, "sleep")
        self.assertEqual(state.metrics["activeUntilMs"].value, 0)

    def test_command_result_is_forwarded_to_local_pubsub(self) -> None:
        async def exercise() -> CapabilityCommandResult:
            bus = InMemoryLocalPubSub()
            results: list[CapabilityCommandResult] = []

            async def result_handler(_topic: str, payload: bytes) -> None:
                results.append(CapabilityCommandResult.from_payload(payload))

            await bus.subscribe(build_capability_command_result_topic("clock", "time-aws"), result_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            result = LegacyConnectivityCommandResult(
                adapter_id="time-lambda",
                command_id="cmd-1",
                thing_name="clock",
                status="succeeded",
                message=None,
                observed_at_ms=1714380000000,
            )
            await bridge.handle_mqtt_message(
                build_time_command_result_topic("clock"),
                result.to_json().encode(),
            )
            return results[0]

        result = asyncio.run(exercise())

        self.assertEqual(result.command_id, "cmd-1")
        self.assertEqual(result.status, "succeeded")

    def test_component_entrypoint_retries_startup_failures(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "time_rig"
            / "aws_connectivity.py"
        ).read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--reconnect-delay"', source)
        self.assertIn("while not shutdown_event.is_set():", source)
        self.assertIn("Time AWS connectivity bridge failed; retrying", source)
        loop_start = source.index("while not shutdown_event.is_set():")
        runtime_start = source.index("aws_runtime = build_aws_runtime", loop_start)
        self.assertLess(loop_start, runtime_start)


if __name__ == "__main__":
    unittest.main()
