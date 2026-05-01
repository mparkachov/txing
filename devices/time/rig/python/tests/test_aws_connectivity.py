from __future__ import annotations

import asyncio
import json
import unittest

from rig.connectivity_protocol import (
    CONTROL_IMMEDIATE,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityState,
    build_command_result_topic,
    build_command_topic,
    build_state_topic,
)
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
            await bridge.start()
            command = ConnectivityCommand(
                command_id="cmd-1",
                thing_name="clock",
                power=True,
                reason="redcon=1",
                issued_at_ms=1714380000000,
                deadline_ms=1714380060000,
            )
            await bus.publish(build_command_topic("clock"), command.to_json())
            assert bridge._connection is not None
            return bridge._connection.published[0]  # type: ignore[union-attr]

        published = asyncio.run(exercise())

        self.assertEqual(published["topic"], build_time_command_topic("clock"))
        self.assertTrue(published["retain"])
        payload = json.loads(published["payload"])
        self.assertEqual(payload["commandId"], "cmd-1")
        self.assertTrue(payload["target"]["power"])

    def test_retained_time_state_maps_to_local_matter_connectivity_state(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            states: list[ConnectivityState] = []

            async def state_handler(_topic: str, payload: bytes) -> None:
                states.append(ConnectivityState.from_payload(payload))

            await bus.subscribe(build_state_topic("clock"), state_handler)
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
            await bridge.handle_mqtt_message(build_time_state_topic("clock"), time_state.to_json().encode())
            return states[0]

        state = asyncio.run(exercise())

        self.assertEqual(state.thing_name, "clock")
        self.assertEqual(state.transport, "matter")
        self.assertEqual(state.sleep_model, "matter-icd")
        self.assertEqual(state.control_availability, CONTROL_IMMEDIATE)
        self.assertTrue(state.power)
        self.assertEqual(state.native_identity["currentTimeIso"], "2024-04-29T07:20:00Z")

    def test_command_result_is_forwarded_to_local_pubsub(self) -> None:
        async def exercise() -> ConnectivityCommandResult:
            bus = InMemoryLocalPubSub()
            results: list[ConnectivityCommandResult] = []

            async def result_handler(_topic: str, payload: bytes) -> None:
                results.append(ConnectivityCommandResult.from_payload(payload))

            await bus.subscribe(build_command_result_topic("clock"), result_handler)
            bridge = TimeAwsConnectivityBridge(
                TimeAwsConnectivityConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                connection_factory=FakeConnection,
            )
            result = ConnectivityCommandResult(
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


if __name__ == "__main__":
    unittest.main()
