from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from typing import Any, Callable

try:
    import boto3
except ImportError:
    boto3 = None

from aws.auth import build_aws_runtime, ensure_aws_profile, resolve_aws_region
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from rig.connectivity_protocol import (
    COMMAND_TOPIC_PREFIX,
    CONTROL_EVENTUAL,
    CONTROL_IMMEDIATE,
    INVENTORY_TOPIC,
    PRESENCE_ONLINE,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_MATTER_ICD,
    TRANSPORT_MATTER,
    build_command_result_topic,
    build_state_topic,
    parse_command_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub

from .time_topics import (
    TIME_MODE_ACTIVE,
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
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        await self.connect()
        await self._bus.subscribe(INVENTORY_TOPIC, self._handle_inventory)
        await self._bus.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", self._handle_local_command)

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
        if self._connection is None:
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connection = None

    async def _handle_inventory(self, _topic: str, payload: bytes) -> None:
        inventory = ConnectivityInventory.from_payload(payload)
        self._managed_things = {
            device.thing_name
            for device in inventory.devices
            if device.transport == TRANSPORT_MATTER
            and device.sleep_model == SLEEP_MODEL_MATTER_ICD
        }
        LOGGER.info("Time AWS connectivity inventory devices=%s", len(self._managed_things))

    async def _handle_local_command(self, topic: str, payload: bytes) -> None:
        thing_name = parse_command_topic(topic)
        if thing_name is None:
            return
        command = ConnectivityCommand.from_payload(payload)
        if command.thing_name != thing_name:
            raise ValueError(
                f"command topic thing={thing_name} differs from payload thing={command.thing_name}"
            )
        if self._managed_things and thing_name not in self._managed_things:
            LOGGER.debug("Ignoring command for unmanaged time thing=%s", thing_name)
            return
        if self._connection is None:
            raise RuntimeError("time AWS connectivity bridge is not connected")
        await self._connection.publish(
            build_time_command_topic(thing_name),
            command.to_json(),
            retain=True,
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info(
            "Published retained time command thing=%s command_id=%s power=%s",
            thing_name,
            command.command_id,
            command.power,
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
            await self._bus.publish(build_command_result_topic(result.thing_name), result.to_json())

    async def publish_connectivity_state(self, state: TimeDeviceState) -> None:
        self._seq += 1
        control_availability = (
            CONTROL_IMMEDIATE
            if state.mode == TIME_MODE_ACTIVE and state.mcp_available
            else CONTROL_EVENTUAL
        )
        connectivity_state = ConnectivityState(
            adapter_id=self._config.adapter_id,
            thing_name=state.thing_name,
            transport=TRANSPORT_MATTER,
            native_identity={
                "currentTimeIso": state.current_time_iso,
                "activeUntilMs": state.active_until_ms,
                "lastCommandId": state.last_command_id,
                "mcpAvailable": state.mcp_available,
            },
            presence=PRESENCE_ONLINE,
            control_availability=control_availability,
            power=state.mode == TIME_MODE_ACTIVE,
            sleep_model=SLEEP_MODEL_MATTER_ICD,
            battery_mv=None,
            observed_at_ms=state.observed_at_ms,
            seq=self._seq,
        )
        await self._bus.publish(build_state_topic(state.thing_name), connectivity_state.to_json())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="time-rig-aws-connectivity",
        description="Bridge time device Greengrass connectivity to retained AWS IoT MQTT topics.",
    )
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--adapter-id", default=os.getenv("ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--iot-endpoint", default=os.getenv("AWS_IOT_ENDPOINT", ""))
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    return parser.parse_args()


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
    aws_runtime = build_aws_runtime(region_name=aws_region, iot_data_endpoint=args.iot_endpoint or None)
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
                try:
                    config = TimeAwsConnectivityConfig(
                        endpoint=aws_runtime.iot_data_endpoint(),
                        aws_region=aws_region,
                        client_id=args.client_id,
                        adapter_id=args.adapter_id,
                    )
                    bridge = TimeAwsConnectivityBridge(
                        config,
                        bus=GreengrassLocalPubSub(),
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
