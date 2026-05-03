from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

try:
    import boto3
except ImportError:
    boto3 = None

from aws.auth import build_aws_runtime, ensure_aws_profile, resolve_aws_region
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from aws.type_catalog import SsmTypeCatalog
from rig.connectivity_protocol import (
    INVENTORY_TOPIC,
    STATE_TOPIC_PREFIX,
    TRANSPORT_MATTER,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_MATTER_ICD,
    parse_state_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import (
    DataType,
    Metric,
    Payload,
    build_device_death_payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    encode_payload,
    utc_timestamp_ms,
)
from rig.thing_registry import AwsThingRegistryClient, ThingRegistration

LOGGER = logging.getLogger("weather_rig.sparkplug_manager")
DEFAULT_RIG_NAME = "server"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_OPERATION_TIMEOUT = 10.0
DEFAULT_RECONNECT_DELAY = 5.0
DEFAULT_INVENTORY_INTERVAL = 10.0
DEFAULT_STALE_AFTER_MS = 130_000
DEFAULT_NODE_BDSEQ = 1
WEATHER_REDCON = 4


@dataclass(slots=True, frozen=True)
class WeatherSparkplugConfig:
    endpoint: str
    aws_region: str
    rig_name: str = DEFAULT_RIG_NAME
    rig_id: str = ""
    sparkplug_group_id: str = DEFAULT_SPARKPLUG_GROUP_ID
    sparkplug_edge_node_id: str = DEFAULT_RIG_NAME
    client_id: str = "weather-sparkplug-manager"
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    operation_timeout: float = DEFAULT_OPERATION_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    inventory_interval: float = DEFAULT_INVENTORY_INTERVAL
    stale_after_ms: int = DEFAULT_STALE_AFTER_MS
    sparkplug_node_bdseq: int = DEFAULT_NODE_BDSEQ


@dataclass(slots=True)
class WeatherManagedDevice:
    registration: ThingRegistration
    last_state: ConnectivityState | None = None
    born: bool = False
    seq: int = 0
    last_reported_at_ms: int = 0
    stale: bool = False
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def thing_name(self) -> str:
        return self.registration.thing_name

    def next_seq(self) -> int:
        seq = self.seq
        self.seq = (self.seq + 1) % 256
        return seq


class WeatherSparkplugManager:
    def __init__(
        self,
        config: WeatherSparkplugConfig,
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
        self._devices: dict[str, WeatherManagedDevice] = {}
        self._inventory_seq = 0
        self._node_seq = 0
        self._node_born = False
        self._state_subscription: object | None = None

    @property
    def devices(self) -> dict[str, WeatherManagedDevice]:
        return self._devices

    def _next_node_seq(self) -> int:
        seq = self._node_seq
        self._node_seq = (self._node_seq + 1) % 256
        return seq

    async def set_registrations(self, registrations: Iterable[ThingRegistration]) -> None:
        next_registrations = {
            registration.thing_name: registration
            for registration in registrations
            if registration.thing_type == "weather"
        }
        for removed in sorted(set(self._devices) - set(next_registrations)):
            await self.publish_device_death(self._devices.pop(removed))
        for thing_name, registration in next_registrations.items():
            self._devices.setdefault(thing_name, WeatherManagedDevice(registration=registration))
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
        self._connection = self._connection_factory(
            mqtt_config,
            aws_runtime=self._aws_runtime,
        )
        await self._connection.connect(timeout_seconds=self._config.connect_timeout)
        LOGGER.info(
            "Connected weather Sparkplug manager endpoint=%s edgeNode=%s",
            self._config.endpoint,
            self._config.sparkplug_edge_node_id,
        )

    async def close(self) -> None:
        for device in list(self._devices.values()):
            if device.born:
                await self.publish_device_death(device)
        await self.publish_node_death()
        if self._state_subscription is not None:
            _close_resource(self._state_subscription)
            self._state_subscription = None
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
        await self.publish_node_birth()
        await self.publish_inventory()

    async def publish_inventory(self) -> None:
        self._inventory_seq += 1
        inventory = ConnectivityInventory(
            adapter_id="weather-sparkplug-manager",
            seq=self._inventory_seq,
            issued_at_ms=utc_timestamp_ms(),
            devices=tuple(
                ConnectivityDeviceConfig(
                    thing_name=device.thing_name,
                    transport=TRANSPORT_MATTER,
                    native_identity={"thingType": "weather"},
                    sleep_model=SLEEP_MODEL_MATTER_ICD,
                )
                for device in self._devices.values()
            ),
        )
        await self._bus.publish(INVENTORY_TOPIC, inventory.to_json())

    async def publish_node_birth(self) -> None:
        if self._connection is None:
            raise RuntimeError("weather Sparkplug manager is not connected")
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
                "Ignoring weather connectivity state topic/payload mismatch topic=%s payloadThing=%s",
                topic,
                state.thing_name,
            )
            return
        await self.apply_connectivity_state(state)

    async def apply_connectivity_state(self, state: ConnectivityState) -> None:
        device = self._devices.get(state.thing_name)
        if device is None:
            LOGGER.debug("Ignoring state for unmanaged weather thing=%s", state.thing_name)
            return
        async with device.operation_lock:
            device.last_state = state
            device.last_reported_at_ms = state.observed_at_ms
            device.stale = False
            if not device.born:
                await self.publish_device_birth(device)
            else:
                await self.publish_device_data(device)

    async def publish_device_birth(self, device: WeatherManagedDevice) -> None:
        await self._publish_device_report(device, message_type="DBIRTH")
        device.born = True

    async def publish_device_data(self, device: WeatherManagedDevice) -> None:
        if not device.born:
            await self.publish_device_birth(device)
            return
        await self._publish_device_report(device, message_type="DDATA")

    async def _publish_device_report(self, device: WeatherManagedDevice, *, message_type: str) -> None:
        if self._connection is None:
            raise RuntimeError("weather Sparkplug manager is not connected")
        state = device.last_state
        topic = build_device_topic(
            self._config.sparkplug_group_id,
            message_type,
            self._config.sparkplug_edge_node_id,
            device.thing_name,
        )
        await self._connection.publish(
            topic,
            encode_payload(
                Payload(
                    timestamp=utc_timestamp_ms(),
                    metrics=_weather_report_metrics(state),
                    seq=device.next_seq(),
                )
            ),
            timeout_seconds=self._config.operation_timeout,
        )
        LOGGER.info(
            "Published weather Sparkplug %s thing=%s redcon=%s presence=%s hasWeather=%s hasBattery=%s",
            message_type,
            device.thing_name,
            WEATHER_REDCON,
            state.presence if state is not None else "unknown",
            state is not None and state.weather is not None,
            state is not None and state.battery_mv is not None,
        )

    async def publish_device_death(self, device: WeatherManagedDevice) -> None:
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


def _weather_report_metrics(state: ConnectivityState | None) -> tuple[Metric, ...]:
    metrics = [
        Metric(name="redcon", datatype=DataType.INT32, int_value=WEATHER_REDCON),
    ]
    if state is not None and state.battery_mv is not None:
        metrics.append(
            Metric(
                name="batteryMv",
                datatype=DataType.INT32,
                int_value=state.battery_mv,
            )
        )
    metrics.extend(_weather_metrics(state))
    return tuple(metrics)


def _weather_metrics(state: ConnectivityState | None) -> tuple[Metric, ...]:
    if state is None or state.weather is None:
        return ()
    metrics: list[Metric] = []
    if state.weather.measured_temperature is not None:
        metrics.append(
            Metric(
                name="measuredTemperature",
                datatype=DataType.DOUBLE,
                double_value=state.weather.measured_temperature,
            )
        )
    if state.weather.measured_pressure is not None:
        metrics.append(
            Metric(
                name="measuredPressure",
                datatype=DataType.DOUBLE,
                double_value=state.weather.measured_pressure,
            )
        )
    if state.weather.measured_humidity is not None:
        metrics.append(
            Metric(
                name="measuredHumidity",
                datatype=DataType.DOUBLE,
                double_value=state.weather.measured_humidity,
            )
        )
    return tuple(metrics)


async def run_weather_sparkplug_manager(
    *,
    config: WeatherSparkplugConfig,
    aws_runtime: Any,
    bus: LocalPubSub,
    registry_client: AwsThingRegistryClient | None = None,
    connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
) -> None:
    registry_client = registry_client or AwsThingRegistryClient(
        aws_runtime.iot_client(),
        type_catalog=SsmTypeCatalog(aws_runtime.client("ssm")),
    )
    registrations = registry_client.list_rig_things(config.rig_id or config.rig_name)
    manager = WeatherSparkplugManager(
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


def _close_resource(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="weather-rig-sparkplug-manager",
        description="Sparkplug lifecycle manager for Matter weather devices.",
    )
    parser.add_argument("--rig-name", default=_env_text("RIG_NAME", DEFAULT_RIG_NAME))
    parser.add_argument("--rig-id", default=_env_text("TXING_RIG_ID", _env_text("RIG_ID", "")))
    parser.add_argument("--sparkplug-group-id", default=_env_text("SPARKPLUG_GROUP_ID", DEFAULT_SPARKPLUG_GROUP_ID))
    parser.add_argument("--sparkplug-edge-node-id", default=_env_text("SPARKPLUG_EDGE_NODE_ID", DEFAULT_RIG_NAME))
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", "weather-sparkplug-manager"))
    parser.add_argument("--iot-endpoint", default=os.getenv("AWS_IOT_ENDPOINT", ""))
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if boto3 is None:
        print("weather-rig-sparkplug-manager start failed: boto3 is required", flush=True)
        raise SystemExit(2)
    ensure_aws_profile("AWS_RIG_PROFILE")
    aws_region = resolve_aws_region()
    if not aws_region:
        print("weather-rig-sparkplug-manager start failed: AWS region is not configured", flush=True)
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
                    config = WeatherSparkplugConfig(
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
                        await run_weather_sparkplug_manager(
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
                        "Weather Sparkplug manager failed; retrying in %.1f seconds",
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
