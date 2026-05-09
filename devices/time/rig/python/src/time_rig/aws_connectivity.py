from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Callable

try:
    import boto3
except ImportError:
    boto3 = None

from aws.auth import build_aws_runtime, ensure_aws_profile, resolve_aws_region
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from rig.capability_protocol import (
    CAPABILITY_COMMAND_TOPIC_PREFIX,
    COMMAND_ACCEPTED,
    HEARTBEAT_RUNNING,
    INVENTORY_TOPIC,
    CapabilityCommand,
    CapabilityCommandResult,
    CapabilityHeartbeat,
    CapabilityInventory,
    CapabilityState,
    SparkplugMetricValue,
    build_capability_command_result_topic,
    build_capability_heartbeat_topic,
    build_capability_state_topic,
    parse_capability_command_topic,
)
from rig.connectivity_protocol import (
    ConnectivityCommandResult,
    ConnectivityCommand as LegacyConnectivityCommand,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

from .time_topics import (
    TIME_MODE_ACTIVE,
    TIME_MODE_SLEEP,
    TimeDeviceState,
    build_time_command_topic,
    parse_time_service_topic,
)

LOGGER = logging.getLogger("time_rig.aws_connectivity")
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_OPERATION_TIMEOUT = 10.0
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_CLIENT_ID = "time-aws-connectivity"
DEFAULT_ADAPTER_ID = "time-aws"
DEFAULT_HEARTBEAT_INTERVAL = 10.0
TIME_CAPABILITY = "time"
MCP_CAPABILITY = "mcp"
SPARKPLUG_CAPABILITY = "sparkplug"
TIME_STATE_SUBSCRIPTION = "txings/+/time/state"
TIME_COMMAND_RESULT_SUBSCRIPTION = "txings/+/time/command-result"


@dataclass(slots=True, frozen=True)
class TimeAwsConnectivityConfig:
    endpoint: str
    aws_region: str
    client_id: str = DEFAULT_CLIENT_ID
    adapter_id: str = DEFAULT_ADAPTER_ID
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    operation_timeout: float = DEFAULT_OPERATION_TIMEOUT
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL


class TimeAwsConnectivityBridge:
    def __init__(
        self,
        config: TimeAwsConnectivityConfig,
        *,
        bus: LocalPubSub,
        connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
        aws_runtime: Any | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._connection_factory = connection_factory
        self._aws_runtime = aws_runtime
        self._connection: Any | None = None
        self._managed_things: set[str] = set()
        self._pending_command_redcon: dict[str, int] = {}
        self._latest_time_states: dict[str, TimeDeviceState] = {}
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._local_subscriptions: list[object] = []
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.connect()
        if not self._local_subscriptions:
            self._local_subscriptions.append(
                await self._bus.subscribe(INVENTORY_TOPIC, self._handle_inventory)
            )
            self._local_subscriptions.append(
                await self._bus.subscribe(
                    f"{CAPABILITY_COMMAND_TOPIC_PREFIX}/+",
                    self._handle_local_command,
                )
            )
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._loop = asyncio.get_running_loop()
        mqtt_config = AwsMqttConnectionConfig(
            endpoint=self._config.endpoint,
            client_id=self._config.client_id,
            region_name=self._config.aws_region,
            connect_timeout_seconds=self._config.connect_timeout,
            operation_timeout_seconds=self._config.operation_timeout,
            keep_alive_seconds=60,
        )
        self._connection = self._connection_factory(
            mqtt_config,
            aws_runtime=self._aws_runtime,
        )
        await self._connection.connect(timeout_seconds=self._config.connect_timeout)
        await self._connection.subscribe(
            TIME_STATE_SUBSCRIPTION,
            self._on_mqtt_message,
            timeout_seconds=self._config.operation_timeout,
        )
        await self._connection.subscribe(
            TIME_COMMAND_RESULT_SUBSCRIPTION,
            self._on_mqtt_message,
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info("Connected time AWS connectivity bridge endpoint=%s", self._config.endpoint)

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            self._heartbeat_task = None
        for subscription in self._local_subscriptions:
            _close_resource(subscription)
        self._local_subscriptions.clear()
        if self._connection is None:
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connection = None

    async def _handle_inventory(self, _topic: str, payload: bytes) -> None:
        inventory = CapabilityInventory.from_payload(payload)
        self._managed_things = {
            device.thing_name
            for device in inventory.devices
            if TIME_CAPABILITY in device.capabilities
        }
        LOGGER.info("Time AWS connectivity inventory devices=%s", len(self._managed_things))

    async def _handle_local_command(self, topic: str, payload: bytes) -> None:
        thing_name = parse_capability_command_topic(topic)
        if thing_name is None:
            return
        command = CapabilityCommand.from_payload(payload)
        if command.thing_name != thing_name:
            raise ValueError(
                f"command topic thing={thing_name} differs from payload thing={command.thing_name}"
            )
        if self._managed_things and thing_name not in self._managed_things:
            LOGGER.debug("Ignoring command for unmanaged time thing=%s", thing_name)
            return
        if self._connection is None:
            raise RuntimeError("time AWS connectivity bridge is not connected")
        self._pending_command_redcon[command.command_id] = command.redcon
        await self._bus.publish(
            build_capability_command_result_topic(thing_name, self._config.adapter_id),
            CapabilityCommandResult(
                adapter_id=self._config.adapter_id,
                command_id=command.command_id,
                thing_name=thing_name,
                status=COMMAND_ACCEPTED,
                redcon=command.redcon,
                message=None,
                observed_at_ms=command.issued_at_ms,
                seq=command.seq,
            ).to_json(),
        )
        legacy_command = LegacyConnectivityCommand(
            command_id=command.command_id,
            thing_name=command.thing_name,
            power=command.redcon < 4,
            reason=command.reason,
            issued_at_ms=command.issued_at_ms,
            deadline_ms=command.deadline_ms,
            seq=command.seq,
        )
        await self._connection.publish(
            build_time_command_topic(thing_name),
            legacy_command.to_json(),
            retain=True,
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info(
            "Published retained time command thing=%s command_id=%s redcon=%s legacyPower=%s",
            thing_name,
            command.command_id,
            command.redcon,
            legacy_command.power,
        )

    def _on_mqtt_message(self, topic: str, payload: bytes) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.handle_mqtt_message(topic, payload))
        )

    async def handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        parsed = parse_time_service_topic(topic)
        if parsed is None:
            return
        thing_name, kind = parsed
        if self._managed_things and thing_name not in self._managed_things:
            LOGGER.debug("Ignoring MQTT message for unmanaged time thing=%s", thing_name)
            return
        if kind == "state":
            await self.publish_connectivity_state(TimeDeviceState.from_payload(payload))
            return
        if kind == "command-result":
            result = ConnectivityCommandResult.from_payload(payload)
            redcon = self._pending_command_redcon.pop(result.command_id, None)
            await self._bus.publish(
                build_capability_command_result_topic(
                    result.thing_name,
                    self._config.adapter_id,
                ),
                CapabilityCommandResult(
                    adapter_id=self._config.adapter_id,
                    command_id=result.command_id,
                    thing_name=result.thing_name,
                    status=result.status,
                    redcon=redcon,
                    message=result.message,
                    observed_at_ms=result.observed_at_ms,
                    seq=result.seq,
                ).to_json(),
            )

    async def publish_connectivity_state(
        self,
        state: TimeDeviceState,
        *,
        observed_at_ms: int | None = None,
    ) -> None:
        state = _effective_time_state(
            state,
            observed_at_ms if observed_at_ms is not None else utc_timestamp_ms(),
        )
        self._latest_time_states[state.thing_name] = state
        self._seq += 1
        metrics: dict[str, SparkplugMetricValue] = {
            "currentTimeIso": SparkplugMetricValue("String", state.current_time_iso),
            "mode": SparkplugMetricValue("String", state.mode),
            "mcpAvailable": SparkplugMetricValue("Boolean", state.mcp_available),
        }
        if state.active_until_ms is not None:
            metrics["activeUntilMs"] = SparkplugMetricValue("Int64", state.active_until_ms)
        if state.last_command_id is not None:
            metrics["lastCommandId"] = SparkplugMetricValue("String", state.last_command_id)
        capability_state = CapabilityState(
            adapter_id=self._config.adapter_id,
            thing_name=state.thing_name,
            capabilities={
                SPARKPLUG_CAPABILITY: True,
                TIME_CAPABILITY: state.mode == TIME_MODE_ACTIVE,
                MCP_CAPABILITY: state.mcp_available,
            },
            metrics=metrics,
            observed_at_ms=observed_at_ms if observed_at_ms is not None else state.observed_at_ms,
            seq=self._seq,
        )
        await self._bus.publish(
            build_capability_state_topic(state.thing_name, self._config.adapter_id),
            capability_state.to_json(),
        )

    async def _publish_heartbeat(self, seq: int) -> None:
        observed_at_ms = utc_timestamp_ms()
        await self._bus.publish(
            build_capability_heartbeat_topic(self._config.adapter_id),
            CapabilityHeartbeat(
                adapter_id=self._config.adapter_id,
                status=HEARTBEAT_RUNNING,
                active_thing_name=None,
                observed_at_ms=observed_at_ms,
                seq=seq,
            ).to_json(),
        )
        for state in self._latest_time_states.values():
            await self.publish_connectivity_state(state, observed_at_ms=observed_at_ms)

    async def _heartbeat_loop(self) -> None:
        seq = 0
        while True:
            seq += 1
            await self._publish_heartbeat(seq)
            await asyncio.sleep(self._config.heartbeat_interval)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="time-rig-aws-connectivity",
        description="Bridge time device Greengrass connectivity to retained AWS IoT MQTT topics.",
    )
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--adapter-id", default=os.getenv("ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--iot-endpoint", default=os.getenv("AWS_IOT_ENDPOINT", ""))
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=float(os.getenv("TIME_AWS_HEARTBEAT_INTERVAL", DEFAULT_HEARTBEAT_INTERVAL)),
    )
    return parser.parse_args()


def _effective_time_state(state: TimeDeviceState, now_ms: int) -> TimeDeviceState:
    if (
        state.mode == TIME_MODE_ACTIVE
        and state.active_until_ms is not None
        and state.active_until_ms <= now_ms
    ):
        return replace(
            state,
            current_time_iso=datetime.fromtimestamp(now_ms / 1000, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            mode=TIME_MODE_SLEEP,
            active_until_ms=None,
            observed_at_ms=now_ms,
            mcp_available=False,
        )
    return state


def _close_resource(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if boto3 is None:
        print("time-rig-aws-connectivity start failed: boto3 is required", flush=True)
        raise SystemExit(2)
    ensure_aws_profile("AWS_RIG_PROFILE")
    aws_region = resolve_aws_region()
    if not aws_region:
        print("time-rig-aws-connectivity start failed: AWS region is not configured", flush=True)
        raise SystemExit(2)

    async def _runner() -> None:
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def _request_shutdown() -> None:
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                break

        async def _bridge_loop() -> None:
            while not shutdown_event.is_set():
                bridge: TimeAwsConnectivityBridge | None = None
                bus: GreengrassLocalPubSub | None = None
                try:
                    aws_runtime = build_aws_runtime(
                        region_name=aws_region,
                        iot_data_endpoint=args.iot_endpoint or None,
                    )
                    config = TimeAwsConnectivityConfig(
                        endpoint=aws_runtime.iot_data_endpoint(),
                        aws_region=aws_region,
                        client_id=args.client_id,
                        adapter_id=args.adapter_id,
                        heartbeat_interval=args.heartbeat_interval,
                    )
                    bus = GreengrassLocalPubSub()
                    bridge = TimeAwsConnectivityBridge(
                        config,
                        bus=bus,
                        aws_runtime=aws_runtime,
                    )
                    await bridge.start()
                    await shutdown_event.wait()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Time AWS connectivity bridge failed; retrying in %.1f seconds",
                        args.reconnect_delay,
                    )
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(),
                            timeout=args.reconnect_delay,
                        )
                    except TimeoutError:
                        continue
                finally:
                    if bridge is not None:
                        await bridge.close()
                    if bus is not None:
                        bus.close()

        bridge_task = asyncio.create_task(_bridge_loop())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            {bridge_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for pending_task in pending:
            pending_task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for done_task in done:
            done_task.result()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
