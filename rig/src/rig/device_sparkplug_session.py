from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from aws.auth import AwsRuntime
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig

from .sparkplug import (
    build_device_death_payload,
    build_device_report_payload,
    build_device_topic,
)

LOGGER = logging.getLogger("rig.device_sparkplug_session")

DEFAULT_DEVICE_CONNECT_TIMEOUT = 20.0
DEFAULT_DEVICE_PUBLISH_TIMEOUT = 10.0
DEFAULT_DEVICE_RECONNECT_DELAY = 5.0

PayloadFactory = Callable[[int], bytes]


@dataclass(slots=True, frozen=True)
class SparkplugMqttSessionConfig:
    endpoint: str
    aws_region: str
    sparkplug_group_id: str
    sparkplug_edge_node_id: str
    client_id: str
    connect_timeout: float = DEFAULT_DEVICE_CONNECT_TIMEOUT
    publish_timeout: float = DEFAULT_DEVICE_PUBLISH_TIMEOUT
    reconnect_delay: float = DEFAULT_DEVICE_RECONNECT_DELAY


class DeviceSparkplugMqttSession:
    """Per-device Sparkplug MQTT session.

    The session uses the managed thing name as the MQTT client id. AWS IoT uses
    that client id for the thing connection indicator, so device-type managers
    should create this session when the underlying device is reachable and tear
    it down when it is not.
    """

    def __init__(
        self,
        config: SparkplugMqttSessionConfig,
        *,
        thing_name: str,
        aws_runtime: AwsRuntime,
        connection_factory: Callable[..., Any] = AwsIotWebsocketConnection,
    ) -> None:
        self._config = config
        self._thing_name = thing_name
        self._aws_runtime = aws_runtime
        self._connection_factory = connection_factory
        self._connection: Any | None = None
        self._operation_lock = asyncio.Lock()
        self._connected = False
        self._disconnectable = False
        self._born = False
        self._seq = 0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def born(self) -> bool:
        return self._born

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    def _build_connection(self) -> Any:
        will_topic = build_device_topic(
            self._config.sparkplug_group_id,
            "DDEATH",
            self._config.sparkplug_edge_node_id,
            self._thing_name,
        )
        will_payload = build_device_death_payload(seq=self._next_seq())
        mqtt_config = AwsMqttConnectionConfig(
            endpoint=self._config.endpoint,
            client_id=self._config.client_id,
            region_name=self._config.aws_region,
            connect_timeout_seconds=self._config.connect_timeout,
            operation_timeout_seconds=self._config.publish_timeout,
            reconnect_min_timeout_seconds=1,
            reconnect_max_timeout_seconds=30,
            keep_alive_seconds=60,
            will_topic=will_topic,
            will_payload=will_payload,
        )
        return self._connection_factory(
            mqtt_config,
            aws_runtime=self._aws_runtime,
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_failure=self._on_connection_failure,
            on_connection_closed=self._on_connection_closed,
        )

    def _on_connection_interrupted(self, error: Exception) -> None:
        LOGGER.warning(
            "Device Sparkplug MQTT session interrupted thing=%s clientId=%s error=%s",
            self._thing_name,
            self._config.client_id,
            error,
        )
        self._connected = False
        self._born = False

    def _on_connection_failure(self, callback_data: Any) -> None:
        LOGGER.warning(
            "Device Sparkplug MQTT session connection failed thing=%s clientId=%s reason=%s",
            self._thing_name,
            self._config.client_id,
            getattr(callback_data, "error", callback_data),
        )
        self._connected = False
        self._born = False

    def _on_connection_closed(self, callback_data: Any) -> None:
        LOGGER.warning(
            "Device Sparkplug MQTT session closed thing=%s clientId=%s reason=%s",
            self._thing_name,
            self._config.client_id,
            getattr(callback_data, "error", callback_data),
        )
        self._connected = False
        self._born = False

    async def _connect_unlocked(self) -> None:
        if self._connected:
            return
        if self._connection is not None:
            await self._disconnect_unlocked()
        will_topic = build_device_topic(
            self._config.sparkplug_group_id,
            "DDEATH",
            self._config.sparkplug_edge_node_id,
            self._thing_name,
        )
        LOGGER.info(
            "Connecting Device Sparkplug MQTT session thing=%s clientId=%s willTopic=%s",
            self._thing_name,
            self._config.client_id,
            will_topic,
        )
        connection = self._build_connection()
        self._connection = connection
        try:
            await connection.connect(timeout_seconds=self._config.connect_timeout)
        except Exception:
            self._connected = False
            self._born = False
            self._disconnectable = False
            self._connection = None
            raise
        self._connected = True
        self._disconnectable = True
        LOGGER.info(
            "Connected Device Sparkplug MQTT session thing=%s clientId=%s",
            self._thing_name,
            self._config.client_id,
        )

    async def connect(self) -> None:
        async with self._operation_lock:
            await self._connect_unlocked()

    async def publish_birth_payload(self, payload_factory: PayloadFactory) -> None:
        async with self._operation_lock:
            if self._connected and self._born:
                return
            await self._connect_unlocked()
            assert self._connection is not None
            topic = build_device_topic(
                self._config.sparkplug_group_id,
                "DBIRTH",
                self._config.sparkplug_edge_node_id,
                self._thing_name,
            )
            await self._connection.publish(
                topic,
                payload_factory(self._next_seq()),
                timeout_seconds=self._config.publish_timeout,
            )
            self._born = True
        LOGGER.info("Published Sparkplug DBIRTH thing=%s topic=%s", self._thing_name, topic)

    async def publish_birth(self, *, redcon: int, battery_mv: int) -> None:
        await self.publish_birth_payload(
            lambda seq: build_device_report_payload(
                redcon=redcon,
                battery_mv=battery_mv,
                seq=seq,
            )
        )

    async def publish_data_payload(self, payload_factory: PayloadFactory) -> bool:
        async with self._operation_lock:
            if not self._connected or not self._born or self._connection is None:
                return False
            topic = build_device_topic(
                self._config.sparkplug_group_id,
                "DDATA",
                self._config.sparkplug_edge_node_id,
                self._thing_name,
            )
            await self._connection.publish(
                topic,
                payload_factory(self._next_seq()),
                timeout_seconds=self._config.publish_timeout,
            )
        LOGGER.info("Published Sparkplug DDATA thing=%s topic=%s", self._thing_name, topic)
        return True

    async def publish_data(self, *, redcon: int, battery_mv: int) -> None:
        await self.publish_data_payload(
            lambda seq: build_device_report_payload(
                redcon=redcon,
                battery_mv=battery_mv,
                seq=seq,
            )
        )

    async def _publish_death_unlocked(self) -> None:
        if not self._connected or self._connection is None:
            self._born = False
            return
        topic = build_device_topic(
            self._config.sparkplug_group_id,
            "DDEATH",
            self._config.sparkplug_edge_node_id,
            self._thing_name,
        )
        await self._connection.publish(
            topic,
            build_device_death_payload(seq=self._next_seq()),
            timeout_seconds=self._config.publish_timeout,
        )
        self._born = False
        LOGGER.info("Published Sparkplug DDEATH thing=%s topic=%s", self._thing_name, topic)

    async def publish_death(self) -> None:
        async with self._operation_lock:
            await self._publish_death_unlocked()

    async def _disconnect_unlocked(self) -> None:
        if self._connection is None:
            self._connected = False
            self._disconnectable = False
            return
        if not self._disconnectable:
            self._connected = False
            self._connection = None
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connected = False
            self._disconnectable = False
            self._connection = None

    async def disconnect(self) -> None:
        async with self._operation_lock:
            await self._disconnect_unlocked()

    async def teardown(self, *, explicit_death: bool) -> None:
        async with self._operation_lock:
            if explicit_death:
                await self._publish_death_unlocked()
            await self._disconnect_unlocked()
