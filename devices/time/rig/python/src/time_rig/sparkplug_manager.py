from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from uuid import uuid4

try:
    import boto3
except ImportError:
    boto3 = None

from aws.auth import build_aws_runtime, ensure_aws_profile, resolve_aws_region
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from rig.connectivity_protocol import (
    CONTROL_IMMEDIATE,
    CONTROL_UNAVAILABLE,
    INVENTORY_TOPIC,
    PRESENCE_ONLINE,
    ConnectivityCommand,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_MATTER_ICD,
    STATE_TOPIC_PREFIX,
    TRANSPORT_MATTER,
    build_command_topic,
    parse_state_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import (
    DataType,
    Metric,
    build_device_death_payload,
    build_device_report_payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    decode_redcon_command,
    utc_timestamp_ms,
)
from rig.thing_registry import AwsThingRegistryClient, ThingGroupNotFoundError, ThingRegistration

LOGGER = logging.getLogger("time_rig.sparkplug_manager")
DEFAULT_RIG_NAME = "aws"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_OPERATION_TIMEOUT = 10.0
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_INVENTORY_INTERVAL = 10.0
DEFAULT_STALE_AFTER_MS = 130_000
DEFAULT_COMMAND_DEADLINE_MS = 60_000
DEFAULT_NODE_BDSEQ = 1


@dataclass(slots=True, frozen=True)
class TimeSparkplugConfig:
    endpoint: str
    aws_region: str
    rig_name: str = DEFAULT_RIG_NAME
    sparkplug_group_id: str = DEFAULT_SPARKPLUG_GROUP_ID
    sparkplug_edge_node_id: str = DEFAULT_RIG_NAME
    client_id: str = "time-sparkplug-manager"
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    operation_timeout: float = DEFAULT_OPERATION_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    inventory_interval: float = DEFAULT_INVENTORY_INTERVAL
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    command_deadline_ms: int = DEFAULT_COMMAND_DEADLINE_MS
    sparkplug_node_bdseq: int = DEFAULT_NODE_BDSEQ


@dataclass(slots=True)
class TimeManagedDevice:
    registration: ThingRegistration
    last_state: ConnectivityState | None = None
    born: bool = False
    redcon: int = 4
    seq: int = 0
    last_reported_at_ms: int = 0
    last_command_redcon: int | None = None
    stale: bool = False
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def thing_name(self) -> str:
        return self.registration.thing_name

    def next_seq(self) -> int:
        seq = self.seq
        self.seq = (self.seq + 1) % 256
        return seq


class TimeSparkplugManager:
    def __init__(
        self,
        config: TimeSparkplugConfig,
        *,
        bus: LocalPubSub,
        aws_runtime: Any,
        connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
    ) -> None:
        self._config = config
        self._bus = bus
        self._aws_runtime = aws_runtime
        self._connection_factory = connection_factory
        self._connection: Any | None = None
        self._devices: dict[str, TimeManagedDevice] = {}
        self._inventory_seq = 0
        self._command_seq = 0
        self._node_seq = 0
        self._node_born = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def devices(self) -> dict[str, TimeManagedDevice]:
        return self._devices

    def _next_node_seq(self) -> int:
        seq = self._node_seq
        self._node_seq = (self._node_seq + 1) % 256
        return seq

    def _next_command_seq(self) -> int:
        seq = self._command_seq
        self._command_seq += 1
        return seq

    async def set_registrations(self, registrations: Iterable[ThingRegistration]) -> None:
        next_registrations = {
            registration.thing_name: registration
            for registration in registrations
            if registration.thing_type == "time"
        }
        for removed in sorted(set(self._devices) - set(next_registrations)):
            await self.publish_device_death(self._devices.pop(removed))
        for thing_name, registration in next_registrations.items():
            self._devices.setdefault(thing_name, TimeManagedDevice(registration=registration))
        await self.publish_inventory()

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._loop = asyncio.get_running_loop()
        will_topic = build_node_topic(
            self._config.sparkplug_group_id,
            "NDEATH",
            self._config.sparkplug_edge_node_id,
        )
        mqtt_config = AwsMqttConnectionConfig(
            endpoint=self._config.endpoint,
            client_id=self._config.client_id,
            region_name=self._config.aws_region,
            connect_timeout_seconds=self._config.connect_timeout,
            operation_timeout_seconds=self._config.operation_timeout,
            keep_alive_seconds=60,
            will_topic=will_topic,
            will_payload=build_node_death_payload(bdseq=self._config.sparkplug_node_bdseq),
        )
        self._connection = self._connection_factory(
            mqtt_config,
            aws_runtime=self._aws_runtime,
        )
        await self._connection.connect(timeout_seconds=self._config.connect_timeout)
        await self._connection.subscribe(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DCMD",
                self._config.sparkplug_edge_node_id,
                "+",
            ),
            self._on_mqtt_message,
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info(
            "Connected time Sparkplug manager endpoint=%s edgeNode=%s",
            self._config.endpoint,
            self._config.sparkplug_edge_node_id,
        )

    async def close(self) -> None:
        for device in list(self._devices.values()):
            if device.born:
                await self.publish_device_death(device)
        await self.publish_node_death()
        if self._connection is None:
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connection = None

    async def start(self) -> None:
        await self.connect()
        await self._bus.subscribe(f"{STATE_TOPIC_PREFIX}/+", self._handle_state_message)
        await self.publish_node_birth()
        await self.publish_inventory()

    async def publish_inventory(self) -> None:
        self._inventory_seq += 1
        inventory = ConnectivityInventory(
            adapter_id="time-sparkplug-manager",
            seq=self._inventory_seq,
            issued_at_ms=utc_timestamp_ms(),
            devices=tuple(
                ConnectivityDeviceConfig(
                    thing_name=device.thing_name,
                    transport=TRANSPORT_MATTER,
                    native_identity={"thingType": "time"},
                    sleep_model=SLEEP_MODEL_MATTER_ICD,
                )
                for device in self._devices.values()
            ),
        )
        await self._bus.publish(INVENTORY_TOPIC, inventory.to_json())

    async def publish_node_birth(self) -> None:
        if self._connection is None:
            raise RuntimeError("time Sparkplug manager is not connected")
        topic = build_node_topic(
            self._config.sparkplug_group_id,
            "NBIRTH",
            self._config.sparkplug_edge_node_id,
        )
        await self._connection.publish(
            topic,
            build_node_birth_payload(
                redcon=1,
                bdseq=self._config.sparkplug_node_bdseq,
                seq=self._next_node_seq(),
            ),
            timeout_seconds=self._config.operation_timeout,
        )
        self._node_born = True

    async def publish_node_death(self) -> None:
        if not self._node_born or self._connection is None:
            return
        topic = build_node_topic(
            self._config.sparkplug_group_id,
            "NDEATH",
            self._config.sparkplug_edge_node_id,
        )
        await self._connection.publish(
            topic,
            build_node_death_payload(bdseq=self._config.sparkplug_node_bdseq),
            timeout_seconds=self._config.operation_timeout,
        )
        self._node_born = False

    async def _handle_state_message(self, topic: str, payload: bytes) -> None:
        thing_name = parse_state_topic(topic)
        if thing_name is None:
            return
        state = ConnectivityState.from_payload(payload)
        if state.thing_name != thing_name:
            LOGGER.warning(
                "Ignoring time connectivity state topic/payload mismatch topic=%s payloadThing=%s",
                topic,
                state.thing_name,
            )
            return
        await self.apply_connectivity_state(state)

    async def apply_connectivity_state(self, state: ConnectivityState) -> None:
        device = self._devices.get(state.thing_name)
        if device is None:
            LOGGER.debug("Ignoring state for unmanaged time thing=%s", state.thing_name)
            return
        async with device.operation_lock:
            device.last_state = state
            device.last_reported_at_ms = state.observed_at_ms
            device.stale = False
            next_redcon = redcon_from_connectivity_state(state)
            changed = next_redcon != device.redcon
            device.redcon = next_redcon
            if not device.born:
                await self.publish_device_birth(device)
            elif changed or device.redcon in (1, 4):
                await self.publish_device_data(device)

    async def publish_device_birth(self, device: TimeManagedDevice) -> None:
        await self._publish_device_report(device, message_type="DBIRTH")
        device.born = True

    async def publish_device_data(self, device: TimeManagedDevice) -> None:
        if not device.born:
            await self.publish_device_birth(device)
            return
        await self._publish_device_report(device, message_type="DDATA")

    async def _publish_device_report(self, device: TimeManagedDevice, *, message_type: str) -> None:
        if self._connection is None:
            raise RuntimeError("time Sparkplug manager is not connected")
        state = device.last_state
        current_time_iso = ""
        if state is not None:
            raw = state.native_identity.get("currentTimeIso")
            if isinstance(raw, str):
                current_time_iso = raw
        topic = build_device_topic(
            self._config.sparkplug_group_id,
            message_type,
            self._config.sparkplug_edge_node_id,
            device.thing_name,
        )
        await self._connection.publish(
            topic,
            build_device_report_payload(
                redcon=device.redcon,
                battery_mv=0,
                seq=device.next_seq(),
                extra_metrics=(
                    Metric(
                        name="currentTimeIso",
                        datatype=DataType.STRING,
                        string_value=current_time_iso,
                    ),
                ),
            ),
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info("Published time Sparkplug %s thing=%s redcon=%s", message_type, device.thing_name, device.redcon)

    async def publish_device_death(self, device: TimeManagedDevice) -> None:
        if self._connection is None:
            return
        topic = build_device_topic(
            self._config.sparkplug_group_id,
            "DDEATH",
            self._config.sparkplug_edge_node_id,
            device.thing_name,
        )
        await self._connection.publish(
            topic,
            build_device_death_payload(seq=device.next_seq()),
            timeout_seconds=self._config.operation_timeout,
        )
        device.born = False
        device.stale = True

    async def publish_connectivity_command(self, device: TimeManagedDevice, redcon: int) -> None:
        command = ConnectivityCommand(
            command_id=str(uuid4()),
            thing_name=device.thing_name,
            power=redcon != 4,
            reason=f"redcon={redcon}",
            issued_at_ms=utc_timestamp_ms(),
            deadline_ms=utc_timestamp_ms() + self._config.command_deadline_ms,
            seq=self._next_command_seq(),
        )
        device.last_command_redcon = redcon
        await self._bus.publish(build_command_topic(device.thing_name), command.to_json())

    async def check_stale_devices(self, now_ms: int | None = None) -> None:
        now_ms = utc_timestamp_ms() if now_ms is None else now_ms
        for device in self._devices.values():
            if not device.born or device.last_reported_at_ms <= 0:
                continue
            if now_ms - device.last_reported_at_ms <= self._config.stale_after_ms:
                continue
            async with device.operation_lock:
                if device.born and now_ms - device.last_reported_at_ms > self._config.stale_after_ms:
                    await self.publish_device_death(device)

    def _on_mqtt_message(self, topic: str, payload: bytes) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.handle_mqtt_message(topic, payload))
        )

    async def handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        prefix = build_device_topic(
            self._config.sparkplug_group_id,
            "DCMD",
            self._config.sparkplug_edge_node_id,
            "",
        ).rstrip("/")
        if not topic.startswith(f"{prefix}/"):
            return
        thing_name = topic.rsplit("/", 1)[-1]
        device = self._devices.get(thing_name)
        if device is None:
            return
        command = decode_redcon_command(payload)
        if command is None:
            LOGGER.warning("Ignoring time DCMD without valid redcon topic=%s", topic)
            return
        await self.publish_connectivity_command(device, command.value)


def redcon_from_connectivity_state(state: ConnectivityState) -> int:
    if state.presence != PRESENCE_ONLINE or state.control_availability == CONTROL_UNAVAILABLE:
        return 4
    if state.power is not True:
        return 4
    if state.control_availability == CONTROL_IMMEDIATE:
        return 1
    return 3


async def run_time_sparkplug_manager(
    *,
    config: TimeSparkplugConfig,
    aws_runtime: Any,
    bus: LocalPubSub,
    registry_client: AwsThingRegistryClient | None = None,
    connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
) -> None:
    registry_client = registry_client or AwsThingRegistryClient(aws_runtime.iot_client())
    try:
        registrations = registry_client.list_rig_things(config.rig_name)
    except ThingGroupNotFoundError:
        LOGGER.warning("Dynamic thing group for rig=%s was not found", config.rig_name)
        registrations = []
    manager = TimeSparkplugManager(
        config,
        bus=bus,
        aws_runtime=aws_runtime,
        connection_factory=connection_factory,
    )
    await manager.set_registrations(registrations)
    await manager.start()

    async def inventory_loop() -> None:
        while True:
            await asyncio.sleep(config.inventory_interval)
            await manager.publish_inventory()

    async def stale_loop() -> None:
        while True:
            await asyncio.sleep(5.0)
            await manager.check_stale_devices()

    tasks = [asyncio.create_task(inventory_loop()), asyncio.create_task(stale_loop())]
    try:
        await asyncio.Future()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await manager.close()


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="time-rig-sparkplug-manager",
        description="Sparkplug lifecycle manager for virtual time devices.",
    )
    parser.add_argument("--rig-name", default=_env_text("RIG_NAME", DEFAULT_RIG_NAME))
    parser.add_argument("--sparkplug-group-id", default=_env_text("SPARKPLUG_GROUP_ID", DEFAULT_SPARKPLUG_GROUP_ID))
    parser.add_argument("--sparkplug-edge-node-id", default=_env_text("SPARKPLUG_EDGE_NODE_ID", DEFAULT_RIG_NAME))
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", "time-sparkplug-manager"))
    parser.add_argument("--iot-endpoint", default=os.getenv("AWS_IOT_ENDPOINT", ""))
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if boto3 is None:
        print("time-rig-sparkplug-manager start failed: boto3 is required", flush=True)
        raise SystemExit(2)
    ensure_aws_profile("AWS_RIG_PROFILE")
    aws_region = resolve_aws_region()
    if not aws_region:
        print("time-rig-sparkplug-manager start failed: AWS region is not configured", flush=True)
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

        async def _manager_loop() -> None:
            while not shutdown_event.is_set():
                try:
                    config = TimeSparkplugConfig(
                        endpoint=aws_runtime.iot_data_endpoint(),
                        aws_region=aws_region,
                        rig_name=args.rig_name,
                        sparkplug_group_id=args.sparkplug_group_id,
                        sparkplug_edge_node_id=args.sparkplug_edge_node_id,
                        client_id=args.client_id,
                        reconnect_delay=args.reconnect_delay,
                    )
                    await run_time_sparkplug_manager(
                        config=config,
                        aws_runtime=aws_runtime,
                        bus=GreengrassLocalPubSub(),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Time Sparkplug manager failed; retrying in %.1f seconds",
                        args.reconnect_delay,
                    )
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(),
                            timeout=args.reconnect_delay,
                        )
                    except TimeoutError:
                        continue

        task = asyncio.create_task(_manager_loop())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait({task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED)
        for pending_task in pending:
            pending_task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for done_task in done:
            done_task.result()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
