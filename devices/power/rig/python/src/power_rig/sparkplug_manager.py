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
from aws.type_catalog import SsmTypeCatalog
from rig.connectivity_protocol import (
    COMMAND_ACCEPTED,
    COMMAND_FAILED,
    COMMAND_RESULT_TOPIC_PREFIX,
    INVENTORY_TOPIC,
    STATE_TOPIC_PREFIX,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
    build_command_topic,
    parse_command_result_topic,
    parse_state_topic,
)
from rig.device_sparkplug_session import (
    DeviceSparkplugMqttSession,
    SparkplugMqttSessionConfig,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import (
    DataType,
    Metric,
    Payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    decode_redcon_command,
    encode_payload,
    utc_timestamp_ms,
)
from rig.thing_registry import AwsThingRegistryClient, ThingRegistration

LOGGER = logging.getLogger("power_rig.sparkplug_manager")
DEFAULT_RIG_NAME = "server"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_OPERATION_TIMEOUT = 10.0
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_STALE_AFTER_MS = 130_000
DEFAULT_NODE_BDSEQ = 1
DEFAULT_INVENTORY_PUBLISH_INTERVAL = 10.0
POWER_COMMAND_DEADLINE_MS = 45_000
POWER_INVENTORY_ADAPTER_ID = "power-sparkplug-manager"
POWER_IDLE_REDCON = 4
POWER_ACTIVE_REDCON = 3


@dataclass(slots=True, frozen=True)
class PowerSparkplugConfig:
    endpoint: str
    aws_region: str
    rig_name: str = DEFAULT_RIG_NAME
    rig_id: str = ""
    sparkplug_group_id: str = DEFAULT_SPARKPLUG_GROUP_ID
    sparkplug_edge_node_id: str = DEFAULT_RIG_NAME
    client_id: str = "power-sparkplug-manager"
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    operation_timeout: float = DEFAULT_OPERATION_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    sparkplug_node_bdseq: int = DEFAULT_NODE_BDSEQ


@dataclass(slots=True)
class PowerManagedDevice:
    registration: ThingRegistration
    last_state: ConnectivityState | None = None
    last_command_result: PowerCommandResultReport | None = None
    born: bool = False
    last_reported_at_ms: int = 0
    stale: bool = False
    redcon: int = POWER_IDLE_REDCON
    target_redcon: int | None = None
    pending_command_targets: dict[str, int] = field(default_factory=dict)
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mqtt_session: DeviceSparkplugMqttSession | None = None

    @property
    def thing_name(self) -> str:
        return self.registration.thing_name


@dataclass(slots=True, frozen=True)
class PowerCommandResultReport:
    command_id: str
    status: str
    target_redcon: int | None
    message: str | None
    observed_at_ms: int
    seq: int


class PowerSparkplugManager:
    def __init__(
        self,
        config: PowerSparkplugConfig,
        *,
        bus: LocalPubSub,
        aws_runtime: Any,
        connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
        session_factory: Callable[..., DeviceSparkplugMqttSession] = DeviceSparkplugMqttSession,
    ) -> None:
        self._config = config
        self._bus = bus
        self._aws_runtime = aws_runtime
        self._connection_factory = connection_factory
        self._session_factory = session_factory
        self._connection: Any | None = None
        self._devices: dict[str, PowerManagedDevice] = {}
        self._node_seq = 0
        self._command_seq = 0
        self._inventory_seq = 0
        self._node_born = False
        self._state_subscription: object | None = None
        self._command_result_subscription: object | None = None
        self._dcmd_subscribed = False

    @property
    def devices(self) -> dict[str, PowerManagedDevice]:
        return self._devices

    def _next_node_seq(self) -> int:
        seq = self._node_seq
        self._node_seq = (self._node_seq + 1) % 256
        return seq

    def _next_command_seq(self) -> int:
        seq = self._command_seq
        self._command_seq += 1
        return seq

    def _device_session_config(self, thing_name: str) -> SparkplugMqttSessionConfig:
        return SparkplugMqttSessionConfig(
            endpoint=self._config.endpoint,
            aws_region=self._config.aws_region,
            sparkplug_group_id=self._config.sparkplug_group_id,
            sparkplug_edge_node_id=self._config.sparkplug_edge_node_id,
            client_id=thing_name,
            connect_timeout=self._config.connect_timeout,
            publish_timeout=self._config.operation_timeout,
            reconnect_delay=self._config.reconnect_delay,
        )

    def _ensure_session(self, device: PowerManagedDevice) -> DeviceSparkplugMqttSession:
        if device.mqtt_session is None:
            device.mqtt_session = self._session_factory(
                self._device_session_config(device.thing_name),
                thing_name=device.thing_name,
                aws_runtime=self._aws_runtime,
            )
        return device.mqtt_session

    async def set_registrations(self, registrations: Iterable[ThingRegistration]) -> None:
        next_registrations = {
            registration.thing_name: registration
            for registration in registrations
            if registration.thing_type == "power"
        }
        for removed in sorted(set(self._devices) - set(next_registrations)):
            await self.publish_device_death(self._devices.pop(removed))
        for thing_name, registration in next_registrations.items():
            self._devices.setdefault(thing_name, PowerManagedDevice(registration=registration))
        await self.publish_inventory()

    async def connect(self) -> None:
        if self._connection is not None:
            return
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
        self._connection = self._connection_factory(mqtt_config, aws_runtime=self._aws_runtime)
        await self._connection.connect(timeout_seconds=self._config.connect_timeout)
        await self._subscribe_device_commands()
        LOGGER.info(
            "Connected power Sparkplug manager endpoint=%s edgeNode=%s",
            self._config.endpoint,
            self._config.sparkplug_edge_node_id,
        )

    async def close(self) -> None:
        for device in list(self._devices.values()):
            if device.born or device.mqtt_session is not None:
                await self.publish_device_death(device)
        await self.publish_node_death()
        if self._state_subscription is not None:
            _close_resource(self._state_subscription)
            self._state_subscription = None
        if self._command_result_subscription is not None:
            _close_resource(self._command_result_subscription)
            self._command_result_subscription = None
        if self._connection is None:
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connection = None

    async def start(self) -> None:
        await self.connect()
        if self._state_subscription is None:
            self._state_subscription = await self._bus.subscribe(
                f"{STATE_TOPIC_PREFIX}/+",
                self._handle_state_message,
            )
        if self._command_result_subscription is None:
            self._command_result_subscription = await self._bus.subscribe(
                f"{COMMAND_RESULT_TOPIC_PREFIX}/+",
                self._handle_command_result_message,
            )
        await self.publish_inventory()
        await self.publish_node_birth()

    async def publish_inventory(self) -> None:
        self._inventory_seq += 1
        devices = tuple(
            ConnectivityDeviceConfig(
                thing_name=device.thing_name,
                transport=TRANSPORT_BLE_GATT,
                native_identity={"bleLocalName": device.thing_name},
                sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
            )
            for device in self._devices.values()
        )
        inventory = ConnectivityInventory(
            adapter_id=POWER_INVENTORY_ADAPTER_ID,
            devices=devices,
            seq=self._inventory_seq,
            issued_at_ms=utc_timestamp_ms(),
        )
        await self._bus.publish(INVENTORY_TOPIC, inventory.to_json())

    async def publish_node_birth(self) -> None:
        if self._connection is None:
            raise RuntimeError("power Sparkplug manager is not connected")
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
                "Ignoring power connectivity state topic/payload mismatch topic=%s payloadThing=%s",
                topic,
                state.thing_name,
            )
            return
        await self.apply_connectivity_state(state)

    async def apply_connectivity_state(self, state: ConnectivityState) -> None:
        if state.sleep_model != SLEEP_MODEL_BLE_CONNECTED_IDLE:
            return
        device = self._devices.get(state.thing_name)
        if device is None:
            LOGGER.debug("Ignoring state for unmanaged power thing=%s", state.thing_name)
            return
        async with device.operation_lock:
            previous_state = device.last_state
            previous_redcon = device.redcon
            next_redcon = _power_redcon_from_state(state)
            device.last_state = state
            device.last_reported_at_ms = state.observed_at_ms
            device.stale = False
            device.redcon = next_redcon
            if not state.reachable:
                if device.born or device.mqtt_session is not None:
                    await self.publish_device_death(device)
                return
            session = self._ensure_session(device)
            try:
                if not session.connected or not session.born or not device.born:
                    await self.publish_device_birth(device)
                elif _power_connected_idle_report(state, next_redcon) or _power_report_changed(
                    previous_redcon=previous_redcon,
                    previous_state=previous_state,
                    redcon=next_redcon,
                    state=state,
                ):
                    await self.publish_device_data(device)
            except Exception as err:
                await self._handle_device_session_error(
                    device,
                    session,
                    action="publish connectivity state",
                    error=err,
                )

    async def _handle_command_result_message(self, topic: str, payload: bytes) -> None:
        thing_name = parse_command_result_topic(topic)
        if thing_name is None:
            return
        result = ConnectivityCommandResult.from_payload(payload)
        if result.thing_name != thing_name:
            LOGGER.warning(
                "Ignoring power connectivity command result topic/payload mismatch topic=%s payloadThing=%s",
                topic,
                result.thing_name,
            )
            return
        await self.apply_connectivity_command_result(result)

    async def apply_connectivity_command_result(self, result: ConnectivityCommandResult) -> None:
        device = self._devices.get(result.thing_name)
        if device is None:
            return
        if result.status == COMMAND_ACCEPTED:
            return
        async with device.operation_lock:
            target_redcon = device.pending_command_targets.pop(result.command_id, None)
            if result.status == COMMAND_FAILED and target_redcon == device.target_redcon:
                device.target_redcon = None
            device.last_command_result = PowerCommandResultReport(
                command_id=result.command_id,
                status=result.status,
                target_redcon=target_redcon,
                message=result.message,
                observed_at_ms=result.observed_at_ms,
                seq=result.seq,
            )
            if not device.born or device.mqtt_session is None:
                return
            try:
                await self.publish_device_data(device)
            except Exception as err:
                await self._handle_device_session_error(
                    device,
                    device.mqtt_session,
                    action="publish command result",
                    error=err,
                )

    async def publish_device_birth(self, device: PowerManagedDevice) -> None:
        session = self._ensure_session(device)
        await session.publish_birth_payload(
            lambda seq: self._build_device_report_payload(device, seq=seq)
        )
        device.born = session.born
        self._log_device_report(device, message_type="DBIRTH")

    async def publish_device_data(self, device: PowerManagedDevice) -> None:
        session = self._ensure_session(device)
        if not device.born or not session.connected or not session.born:
            await self.publish_device_birth(device)
            return
        published = await session.publish_data_payload(
            lambda seq: self._build_device_report_payload(device, seq=seq)
        )
        if not published:
            await self.publish_device_birth(device)
            return
        self._log_device_report(device, message_type="DDATA")

    def _build_device_report_payload(self, device: PowerManagedDevice, *, seq: int) -> bytes:
        state = device.last_state
        return encode_payload(
            Payload(
                timestamp=utc_timestamp_ms(),
                metrics=(
                    _power_report_metrics(device.redcon, state)
                    + _power_command_result_metrics(device.last_command_result)
                ),
                seq=seq,
            )
        )

    def _log_device_report(self, device: PowerManagedDevice, *, message_type: str) -> None:
        state = device.last_state
        LOGGER.info(
            "Published power Sparkplug %s thing=%s clientId=%s redcon=%s presence=%s hasBattery=%s",
            message_type,
            device.thing_name,
            device.thing_name,
            device.redcon,
            state.presence if state is not None else "unknown",
            state is not None and state.battery_mv is not None,
        )

    async def _handle_device_session_error(
        self,
        device: PowerManagedDevice,
        session: DeviceSparkplugMqttSession,
        *,
        action: str,
        error: Exception,
    ) -> None:
        LOGGER.warning(
            "Power device Sparkplug MQTT %s failed thing=%s redcon=%s reachable=%s error=%s: %s",
            action,
            device.thing_name,
            device.redcon,
            bool(device.last_state and device.last_state.reachable),
            type(error).__name__,
            error,
        )
        device.born = False
        try:
            await session.teardown(explicit_death=False)
        except Exception:
            LOGGER.debug(
                "Power device Sparkplug MQTT cleanup after failure failed thing=%s",
                device.thing_name,
                exc_info=True,
            )

    async def publish_device_death(self, device: PowerManagedDevice) -> None:
        session = device.mqtt_session
        if session is not None:
            await session.teardown(explicit_death=device.born)
        device.born = False
        device.stale = True

    async def check_stale_devices(self, now_ms: int | None = None) -> None:
        now_ms = utc_timestamp_ms() if now_ms is None else now_ms
        for device in self._devices.values():
            if not device.born or device.last_reported_at_ms <= 0:
                continue
            if now_ms - device.last_reported_at_ms <= self._config.stale_after_ms:
                continue
            async with device.operation_lock:
                stale_age_ms = now_ms - device.last_reported_at_ms
                if device.born and stale_age_ms > self._config.stale_after_ms:
                    LOGGER.warning(
                        "Power Sparkplug device stale thing=%s ageMs=%s staleAfterMs=%s",
                        device.thing_name,
                        stale_age_ms,
                        self._config.stale_after_ms,
                    )
                    await self.publish_device_death(device)

    async def _subscribe_device_commands(self) -> None:
        if self._dcmd_subscribed or self._connection is None:
            return
        subscribe = getattr(self._connection, "subscribe", None)
        if not callable(subscribe):
            self._dcmd_subscribed = True
            return
        topic = build_device_topic(
            self._config.sparkplug_group_id,
            "DCMD",
            self._config.sparkplug_edge_node_id,
            "+",
        )
        loop = asyncio.get_running_loop()

        def _on_message(message_topic: str, payload: bytes) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_dcmd_message(message_topic, payload))
            )

        await subscribe(topic, _on_message, timeout_seconds=self._config.operation_timeout)
        self._dcmd_subscribed = True

    async def _handle_dcmd_message(self, topic: str, payload: bytes) -> None:
        thing_name = _parse_power_dcmd_topic(
            topic,
            group_id=self._config.sparkplug_group_id,
            edge_node_id=self._config.sparkplug_edge_node_id,
        )
        if thing_name is None:
            return
        command = decode_redcon_command(payload)
        if command is None:
            LOGGER.warning("Ignoring power DCMD without valid redcon topic=%s", topic)
            return
        device = self._devices.get(thing_name)
        if device is None:
            return
        target_redcon = (
            POWER_ACTIVE_REDCON if command.value < POWER_IDLE_REDCON else POWER_IDLE_REDCON
        )
        issued_at_ms = utc_timestamp_ms()
        if command.seq is None:
            command_seq = self._next_command_seq()
        else:
            command_seq = command.seq
            self._command_seq = max(self._command_seq, command_seq + 1)
        connectivity_command = ConnectivityCommand(
            command_id=str(uuid4()),
            thing_name=device.thing_name,
            power=target_redcon < POWER_IDLE_REDCON,
            reason=f"redcon={command.value}",
            issued_at_ms=issued_at_ms,
            deadline_ms=issued_at_ms + POWER_COMMAND_DEADLINE_MS,
            seq=command_seq,
        )
        async with device.operation_lock:
            device.target_redcon = target_redcon
            device.pending_command_targets[connectivity_command.command_id] = target_redcon
            await self._bus.publish(
                build_command_topic(device.thing_name),
                connectivity_command.to_json(),
            )


def _power_report_metrics(redcon: int, state: ConnectivityState | None) -> tuple[Metric, ...]:
    metrics = [Metric(name="redcon", datatype=DataType.INT32, int_value=redcon)]
    if state is not None and state.battery_mv is not None:
        metrics.append(
            Metric(name="batteryMv", datatype=DataType.INT32, int_value=state.battery_mv)
        )
    return tuple(metrics)


def _power_command_result_metrics(
    command_result: PowerCommandResultReport | None,
) -> tuple[Metric, ...]:
    if command_result is None:
        return ()
    metrics = [
        Metric(
            name="redconCommandStatus",
            datatype=DataType.STRING,
            string_value=command_result.status,
        ),
        Metric(
            name="redconCommandSeq",
            datatype=DataType.INT32,
            int_value=command_result.seq,
        ),
        Metric(
            name="redconCommandObservedAt",
            datatype=DataType.UINT64,
            long_value=command_result.observed_at_ms,
        ),
        Metric(
            name="redconCommandId",
            datatype=DataType.STRING,
            string_value=command_result.command_id,
        ),
    ]
    if command_result.target_redcon is not None:
        metrics.append(
            Metric(
                name="redconCommandTarget",
                datatype=DataType.INT32,
                int_value=command_result.target_redcon,
            )
        )
    if command_result.message:
        metrics.append(
            Metric(
                name="redconCommandMessage",
                datatype=DataType.STRING,
                string_value=command_result.message,
            )
        )
    return tuple(metrics)


def _power_redcon_from_state(state: ConnectivityState | None) -> int:
    if state is None or not state.reachable:
        return POWER_IDLE_REDCON
    return POWER_ACTIVE_REDCON if state.power else POWER_IDLE_REDCON


def _power_report_changed(
    *,
    previous_redcon: int,
    previous_state: ConnectivityState | None,
    redcon: int,
    state: ConnectivityState | None,
) -> bool:
    return _power_report_metrics(previous_redcon, previous_state) != _power_report_metrics(
        redcon,
        state,
    )


def _power_connected_idle_report(state: ConnectivityState, redcon: int) -> bool:
    return (
        redcon == POWER_IDLE_REDCON
        and state.reachable
        and state.native_identity.get("bleConnected") is True
    )


def _parse_power_dcmd_topic(
    topic: str,
    *,
    group_id: str,
    edge_node_id: str,
) -> str | None:
    prefix = f"spBv1.0/{group_id}/DCMD/{edge_node_id}/"
    if not topic.startswith(prefix):
        return None
    suffix = topic[len(prefix) :]
    if not suffix or "/" in suffix:
        return None
    return suffix


async def run_power_sparkplug_manager(
    *,
    config: PowerSparkplugConfig,
    aws_runtime: Any,
    bus: LocalPubSub,
    registry_client: AwsThingRegistryClient | None = None,
    connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
    inventory_publish_interval: float = DEFAULT_INVENTORY_PUBLISH_INTERVAL,
) -> None:
    registry_client = registry_client or AwsThingRegistryClient(
        aws_runtime.iot_client(),
        type_catalog=SsmTypeCatalog(aws_runtime.client("ssm")),
    )
    registrations = registry_client.list_rig_things(config.rig_id or config.rig_name)
    manager = PowerSparkplugManager(
        config,
        bus=bus,
        aws_runtime=aws_runtime,
        connection_factory=connection_factory,
    )
    await manager.set_registrations(registrations)
    await manager.start()

    async def stale_loop() -> None:
        while True:
            await asyncio.sleep(5.0)
            await manager.check_stale_devices()

    async def inventory_loop() -> None:
        while True:
            await asyncio.sleep(inventory_publish_interval)
            await manager.publish_inventory()

    tasks = [asyncio.create_task(stale_loop())]
    if inventory_publish_interval > 0:
        tasks.append(asyncio.create_task(inventory_loop()))
    try:
        await asyncio.Future()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await manager.close()


def _close_resource(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="power-rig-sparkplug-manager",
        description="Sparkplug lifecycle manager for BLE connected-idle power devices.",
    )
    parser.add_argument("--rig-name", default=_env_text("RIG_NAME", DEFAULT_RIG_NAME))
    parser.add_argument("--rig-id", default=_env_text("TXING_RIG_ID", _env_text("RIG_ID", "")))
    parser.add_argument("--sparkplug-group-id", default=_env_text("SPARKPLUG_GROUP_ID", DEFAULT_SPARKPLUG_GROUP_ID))
    parser.add_argument("--sparkplug-edge-node-id", default=_env_text("SPARKPLUG_EDGE_NODE_ID", DEFAULT_RIG_NAME))
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", "power-sparkplug-manager"))
    parser.add_argument("--iot-endpoint", default=os.getenv("AWS_IOT_ENDPOINT", ""))
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if boto3 is None:
        print("power-rig-sparkplug-manager start failed: boto3 is required", flush=True)
        raise SystemExit(2)
    ensure_aws_profile("AWS_RIG_PROFILE")
    aws_region = resolve_aws_region()
    if not aws_region:
        print("power-rig-sparkplug-manager start failed: AWS region is not configured", flush=True)
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

        async def _manager_loop() -> None:
            while not shutdown_event.is_set():
                try:
                    aws_runtime = build_aws_runtime(
                        region_name=aws_region,
                        iot_data_endpoint=args.iot_endpoint or None,
                    )
                    config = PowerSparkplugConfig(
                        endpoint=aws_runtime.iot_data_endpoint(),
                        aws_region=aws_region,
                        rig_name=args.rig_name,
                        rig_id=args.rig_id,
                        sparkplug_group_id=args.sparkplug_group_id,
                        sparkplug_edge_node_id=args.sparkplug_edge_node_id,
                        client_id=args.client_id,
                        reconnect_delay=args.reconnect_delay,
                    )
                    bus = GreengrassLocalPubSub()
                    try:
                        await run_power_sparkplug_manager(
                            config=config,
                            aws_runtime=aws_runtime,
                            bus=bus,
                        )
                    finally:
                        bus.close()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Power Sparkplug manager failed; retrying in %.1f seconds",
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
