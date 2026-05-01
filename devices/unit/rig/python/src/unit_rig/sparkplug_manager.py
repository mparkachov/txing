from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

try:
    import boto3
except ImportError:
    boto3 = None

from aws.auth import (
    AwsRuntime,
    build_aws_runtime,
    ensure_aws_profile,
    resolve_aws_region,
)
from aws.mcp_topics import build_mcp_descriptor_topic, build_mcp_status_topic
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from aws.video_topics import build_video_descriptor_topic, build_video_status_topic

from .ble_bridge import (
    BOARD_SHADOW_NAME,
    DEFAULT_AWS_CONNECT_TIMEOUT,
    DEFAULT_BATTERY_MV,
    DEFAULT_MQTT_PUBLISH_TIMEOUT,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_RIG_NAME,
    DEFAULT_RIG_NAME_ENV,
    DEFAULT_SPARKPLUG_EDGE_NODE_ID,
    DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV,
    DEFAULT_SPARKPLUG_GROUP_ID,
    DEFAULT_SPARKPLUG_GROUP_ID_ENV,
    KNOWN_NAMED_SHADOWS,
    MCP_SHADOW_NAME,
    MCU_SHADOW_NAME,
    SPARKPLUG_SHADOW_NAME,
    VIDEO_SHADOW_NAME,
    AwsShadowClient,
    AwsShadowUpdate,
    BoardVideoState,
    BridgeConfig,
    _build_mcp_shadow_report,
    _calculate_redcon,
    _coerce_optional_int,
    _default_board_video_state,
    _derive_board_video_state,
    _env_text,
    _reported_from_named_shadow,
    _resolve_sparkplug_edge_node_id,
)
from .connectivity_protocol import (
    COMMAND_TOPIC_PREFIX,
    CONTROL_UNAVAILABLE,
    INVENTORY_TOPIC,
    PRESENCE_ONLINE,
    STATE_TOPIC_PREFIX,
    ConnectivityCommand,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    TRANSPORT_BLE_GATT,
    build_command_topic,
    parse_state_topic,
)
from .local_pubsub import GreengrassLocalPubSub, LocalPubSub
from .sparkplug import (
    build_device_death_payload,
    build_device_report_payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    utc_timestamp_ms,
)
from .thing_registry import AwsThingRegistryClient, DeviceRegistration, ThingGroupNotFoundError

LOGGER = logging.getLogger("rig.sparkplug_manager")
DEFAULT_INVENTORY_PUBLISH_INTERVAL = 10.0


@dataclass(slots=True, frozen=True)
class SparkplugMqttSessionConfig:
    endpoint: str
    aws_region: str
    sparkplug_group_id: str
    sparkplug_edge_node_id: str
    client_id: str
    connect_timeout: float = DEFAULT_AWS_CONNECT_TIMEOUT
    publish_timeout: float = DEFAULT_MQTT_PUBLISH_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY


class DeviceSparkplugMqttSession:
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
        self._connected = False
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
            on_connection_closed=self._on_connection_closed,
        )

    def _on_connection_interrupted(self, error: Exception) -> None:
        LOGGER.warning(
            "Device Sparkplug MQTT session interrupted thing=%s error=%s",
            self._thing_name,
            error,
        )
        self._connected = False
        self._born = False

    def _on_connection_closed(self, callback_data: Any) -> None:
        LOGGER.warning(
            "Device Sparkplug MQTT session closed thing=%s reason=%s",
            self._thing_name,
            getattr(callback_data, "error", callback_data),
        )
        self._connected = False
        self._born = False

    async def connect(self) -> None:
        if self._connected:
            return
        self._connection = self._build_connection()
        await self._connection.connect(timeout_seconds=self._config.connect_timeout)
        self._connected = True

    async def publish_birth(self, *, redcon: int, battery_mv: int) -> None:
        await self.connect()
        assert self._connection is not None
        await self._connection.publish(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DBIRTH",
                self._config.sparkplug_edge_node_id,
                self._thing_name,
            ),
            build_device_report_payload(
                redcon=redcon,
                battery_mv=battery_mv,
                seq=self._next_seq(),
            ),
            timeout_seconds=self._config.publish_timeout,
        )
        self._born = True

    async def publish_data(self, *, redcon: int, battery_mv: int) -> None:
        if not self._connected or not self._born or self._connection is None:
            return
        await self._connection.publish(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DDATA",
                self._config.sparkplug_edge_node_id,
                self._thing_name,
            ),
            build_device_report_payload(
                redcon=redcon,
                battery_mv=battery_mv,
                seq=self._next_seq(),
            ),
            timeout_seconds=self._config.publish_timeout,
        )

    async def publish_death(self) -> None:
        if not self._connected or self._connection is None:
            self._born = False
            return
        await self._connection.publish(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DDEATH",
                self._config.sparkplug_edge_node_id,
                self._thing_name,
            ),
            build_device_death_payload(seq=self._next_seq()),
            timeout_seconds=self._config.publish_timeout,
        )
        self._born = False

    async def disconnect(self) -> None:
        if self._connection is None:
            self._connected = False
            return
        try:
            await self._connection.disconnect(timeout_seconds=self._config.connect_timeout)
        finally:
            self._connected = False
            self._connection = None

    async def teardown(self, *, explicit_death: bool) -> None:
        if explicit_death:
            await self.publish_death()
        await self.disconnect()


@dataclass(slots=True)
class ManagedDeviceState:
    registration: DeviceRegistration
    snapshot_version: int | None = None
    connectivity: ConnectivityState | None = None
    target_redcon: int | None = None
    reported_power: bool = False
    reported_online: bool = False
    battery_mv: int = DEFAULT_BATTERY_MV
    ble_device_id: str | None = None
    board_power: bool = False
    board_wifi_online: bool = False
    mcp_descriptor_payload: dict[str, Any] | None = None
    mcp_status_payload: dict[str, Any] | None = None
    video_descriptor_payload: dict[str, Any] | None = None
    video_status_payload: dict[str, Any] | None = None
    mcp_available: bool = False
    board_video: BoardVideoState | None = None
    redcon: int = 4
    redcon_one_staged: bool = False
    mqtt_session: DeviceSparkplugMqttSession | None = None

    @property
    def thing_name(self) -> str:
        return self.registration.thing_name

    def ensure_video_defaults(self, aws_region: str) -> None:
        if self.board_video is None:
            self.board_video = _default_board_video_state(
                thing_name=self.thing_name,
                aws_region=aws_region,
            )

    def reachable(self) -> bool:
        return bool(self.connectivity and self.connectivity.reachable)

    def reconcile_redcon(self) -> bool:
        board_video_ready = False
        if self.board_video is not None:
            board_video_ready = self.board_video.is_ready_for_redcon(utc_timestamp_ms())
        derived = _calculate_redcon(
            ble_online=self.reachable(),
            mcu_power=self.reported_power,
            mcp_available=self.mcp_available,
            board_video_ready=board_video_ready,
        )
        if derived == 1 and self.redcon not in (1, 2):
            derived = 2
            self.redcon_one_staged = True
        else:
            self.redcon_one_staged = False
        if self.redcon == derived:
            return False
        self.redcon = derived
        return True

    def promote_redcon_after_stage(self) -> bool:
        if not self.redcon_one_staged:
            return False
        self.redcon_one_staged = False
        if self.redcon != 2:
            return False
        board_video_ready = False
        if self.board_video is not None:
            board_video_ready = self.board_video.is_ready_for_redcon(utc_timestamp_ms())
        if (
            _calculate_redcon(
                ble_online=self.reachable(),
                mcu_power=self.reported_power,
                mcp_available=self.mcp_available,
                board_video_ready=board_video_ready,
            )
            != 1
        ):
            return False
        self.redcon = 1
        return True

    def clear_target_if_converged(self) -> bool:
        target = self.target_redcon
        if target is None:
            return False
        if target == 4 and self.redcon == 4:
            self.target_redcon = None
            return True
        if target < 4 and self.redcon <= target:
            self.target_redcon = None
            return True
        return False


class SparkplugManager:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        aws_runtime: AwsRuntime,
        bus: LocalPubSub,
        cloud_client: AwsShadowClient,
        session_factory: Callable[..., DeviceSparkplugMqttSession] = DeviceSparkplugMqttSession,
    ) -> None:
        self._config = config
        self._aws_runtime = aws_runtime
        self._bus = bus
        self._cloud_client = cloud_client
        self._session_factory = session_factory
        self._devices: dict[str, ManagedDeviceState] = {}
        self._inventory_seq = 0
        self._command_seq = 0
        self._node_seq = 0
        self._node_born = False

    @property
    def devices(self) -> Mapping[str, ManagedDeviceState]:
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
        safe_thing = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in thing_name)
        return SparkplugMqttSessionConfig(
            endpoint=self._config.iot_endpoint,
            aws_region=self._config.aws_region,
            sparkplug_group_id=self._config.sparkplug_group_id,
            sparkplug_edge_node_id=self._config.sparkplug_edge_node_id,
            client_id=f"rig-{self._config.rig_name}-sp-{safe_thing}",
            connect_timeout=self._config.aws_connect_timeout,
            reconnect_delay=self._config.reconnect_delay,
        )

    def _ensure_session(self, device: ManagedDeviceState) -> DeviceSparkplugMqttSession:
        if device.mqtt_session is None:
            device.mqtt_session = self._session_factory(
                self._device_session_config(device.thing_name),
                thing_name=device.thing_name,
                aws_runtime=self._aws_runtime,
            )
        return device.mqtt_session

    async def set_registrations(
        self,
        registrations: Iterable[DeviceRegistration],
        *,
        snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        snapshots = snapshots or {}
        next_names = {registration.thing_name for registration in registrations}
        for removed_name in sorted(set(self._devices) - next_names):
            await self.remove_device(removed_name)

        for registration in registrations:
            if registration.thing_name in self._devices:
                continue
            device = ManagedDeviceState(registration=registration)
            self._apply_snapshot(device, snapshots.get(registration.thing_name, {}))
            device.ensure_video_defaults(self._config.aws_region)
            device.reconcile_redcon()
            self._devices[registration.thing_name] = device
        await self.publish_inventory()

    async def remove_device(self, thing_name: str) -> None:
        device = self._devices.pop(thing_name, None)
        if device is None:
            return
        if device.mqtt_session is not None:
            await device.mqtt_session.teardown(explicit_death=True)

    def _apply_snapshot(
        self,
        device: ManagedDeviceState,
        snapshot: Mapping[str, Any],
    ) -> None:
        state = snapshot.get("state")
        reported = state.get("reported") if isinstance(state, Mapping) else None
        reported = reported if isinstance(reported, Mapping) else {}
        reported_device = reported.get("device")
        reported_device = reported_device if isinstance(reported_device, Mapping) else {}
        mcu = reported_device.get("mcu")
        mcu = mcu if isinstance(mcu, Mapping) else {}
        board = reported_device.get("board")
        board = board if isinstance(board, Mapping) else {}
        wifi = board.get("wifi")
        wifi = wifi if isinstance(wifi, Mapping) else {}

        power = mcu.get("power")
        online = mcu.get("online")
        battery_mv = reported_device.get("batteryMv")
        board_power = board.get("power")
        board_wifi_online = wifi.get("online")
        if isinstance(power, bool):
            device.reported_power = power
        if isinstance(online, bool):
            device.reported_online = online
        if isinstance(battery_mv, int) and not isinstance(battery_mv, bool):
            device.battery_mv = battery_mv
        if isinstance(board_power, bool):
            device.board_power = board_power
        if isinstance(board_wifi_online, bool):
            device.board_wifi_online = board_wifi_online
        ble_device_id = mcu.get("bleDeviceId")
        if isinstance(ble_device_id, str) and ble_device_id.strip():
            device.ble_device_id = ble_device_id.strip()

        version = _coerce_optional_int(snapshot.get("version"))
        device.snapshot_version = version

    async def publish_inventory(self) -> None:
        self._inventory_seq += 1
        device_configs = tuple(
            ConnectivityDeviceConfig(
                thing_name=device.thing_name,
                transport=TRANSPORT_BLE_GATT,
                native_identity=(
                    {"bleDeviceId": device.ble_device_id}
                    if device.ble_device_id
                    else {}
                ),
                sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
            )
            for device in self._devices.values()
        )
        inventory = ConnectivityInventory(
            adapter_id="sparkplug-manager",
            seq=self._inventory_seq,
            issued_at_ms=utc_timestamp_ms(),
            devices=device_configs,
        )
        await self._bus.publish(INVENTORY_TOPIC, inventory.to_json())
        LOGGER.info(
            "Published connectivity inventory seq=%s devices=%s",
            self._inventory_seq,
            len(device_configs),
        )

    async def apply_connectivity_state(self, state: ConnectivityState) -> None:
        device = self._devices.get(state.thing_name)
        if device is None:
            LOGGER.debug("Ignoring connectivity state for unmanaged thing=%s", state.thing_name)
            return

        previous_reachable = device.reachable()
        previous_redcon = device.redcon
        previous_battery = device.battery_mv
        device.connectivity = state
        device.reported_online = state.reachable
        if state.power is not None:
            device.reported_power = state.power
        if state.battery_mv is not None:
            device.battery_mv = state.battery_mv
        ble_device_id = state.native_identity.get("bleDeviceId")
        if isinstance(ble_device_id, str) and ble_device_id.strip():
            device.ble_device_id = ble_device_id.strip()

        redcon_changed = device.reconcile_redcon()
        await self._publish_mcu_shadow_from_state(device, state)

        if device.reachable():
            session = self._ensure_session(device)
            if not session.connected or not session.born:
                await session.publish_birth(
                    redcon=device.redcon,
                    battery_mv=device.battery_mv,
                )
            elif redcon_changed or previous_battery != device.battery_mv:
                await session.publish_data(
                    redcon=device.redcon,
                    battery_mv=device.battery_mv,
                )
            if device.promote_redcon_after_stage():
                await session.publish_data(
                    redcon=device.redcon,
                    battery_mv=device.battery_mv,
                )
        elif previous_reachable:
            session = device.mqtt_session
            if session is not None:
                await session.teardown(explicit_death=True)

        if previous_redcon != device.redcon:
            device.clear_target_if_converged()

    async def _publish_mcu_shadow_from_state(
        self,
        device: ManagedDeviceState,
        state: ConnectivityState,
    ) -> None:
        mcu_patch: dict[str, Any] = {
            "online": state.reachable,
        }
        if state.power is not None:
            mcu_patch["power"] = state.power
        if device.ble_device_id is not None:
            mcu_patch["bleDeviceId"] = device.ble_device_id
        await self._cloud_client.update_named_shadow_reported(
            thing_name=device.thing_name,
            shadow_name=MCU_SHADOW_NAME,
            reported_patch=mcu_patch,
        )

    async def apply_cloud_updates(self, updates: Iterable[AwsShadowUpdate]) -> None:
        for update in updates:
            device = self._devices.get(update.thing_name)
            if device is None:
                continue
            previous_redcon = device.redcon
            previous_battery = device.battery_mv
            await self._apply_cloud_update(device, update)
            redcon_changed = device.reconcile_redcon()
            session = device.mqtt_session
            if session is not None and session.connected and session.born:
                if redcon_changed or previous_battery != device.battery_mv:
                    await session.publish_data(
                        redcon=device.redcon,
                        battery_mv=device.battery_mv,
                    )
                if device.promote_redcon_after_stage():
                    await session.publish_data(
                        redcon=device.redcon,
                        battery_mv=device.battery_mv,
                    )
            if previous_redcon != device.redcon:
                device.clear_target_if_converged()

    async def _apply_cloud_update(
        self,
        device: ManagedDeviceState,
        update: AwsShadowUpdate,
    ) -> None:
        if update.command_redcon is not None:
            device.target_redcon = update.command_redcon
            await self._publish_connectivity_command(device, update.command_redcon)
        if update.reported_power is not None:
            device.reported_power = update.reported_power
        if update.reported_online is not None:
            device.reported_online = update.reported_online
        if update.ble_device_id_present:
            device.ble_device_id = update.ble_device_id
        if update.battery_mv is not None:
            device.battery_mv = update.battery_mv
        if update.board_power is not None:
            device.board_power = update.board_power
        if update.board_wifi_online is not None:
            device.board_wifi_online = update.board_wifi_online
        if update.mcp_descriptor is not None:
            device.mcp_descriptor_payload = update.mcp_descriptor
        if update.mcp_status is not None:
            device.mcp_status_payload = update.mcp_status
        if update.video_descriptor is not None:
            device.video_descriptor_payload = update.video_descriptor
        if update.video_status is not None:
            device.video_status_payload = update.video_status

        if update.mcp_descriptor is not None or update.mcp_status is not None:
            status = device.mcp_status_payload or {}
            device.mcp_available = bool(status.get("available"))
            await self._cloud_client.update_named_shadow_reported(
                thing_name=device.thing_name,
                shadow_name=MCP_SHADOW_NAME,
                reported_patch=_build_mcp_shadow_report(
                    descriptor_payload=device.mcp_descriptor_payload,
                    status_payload=device.mcp_status_payload,
                ),
            )
        if update.video_descriptor is not None or update.video_status is not None:
            device.board_video = _derive_board_video_state(
                thing_name=device.thing_name,
                aws_region=self._config.aws_region,
                descriptor_payload=device.video_descriptor_payload,
                status_payload=device.video_status_payload,
            )

    async def _publish_connectivity_command(
        self,
        device: ManagedDeviceState,
        target_redcon: int,
    ) -> None:
        command = ConnectivityCommand(
            command_id=str(uuid4()),
            thing_name=device.thing_name,
            power=target_redcon != 4,
            reason=f"redcon={target_redcon}",
            issued_at_ms=utc_timestamp_ms(),
            seq=self._next_command_seq(),
        )
        await self._bus.publish(build_command_topic(device.thing_name), command.to_json())

    async def publish_node_birth(self) -> None:
        await self._cloud_client.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NBIRTH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_birth_payload(
                redcon=1,
                bdseq=self._config.sparkplug_node_bdseq,
                seq=self._next_node_seq(),
            ),
        )
        self._node_born = True

    async def publish_node_death(self) -> None:
        if not self._node_born:
            return
        await self._cloud_client.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NDEATH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_death_payload(
                bdseq=self._config.sparkplug_node_bdseq,
            ),
        )
        self._node_born = False

    async def subscribe_local_state(self) -> None:
        await self._bus.subscribe(f"{STATE_TOPIC_PREFIX}/+", self._handle_state_message)

    async def _handle_state_message(self, topic: str, payload: bytes) -> None:
        thing_name = parse_state_topic(topic)
        if thing_name is None:
            return
        state = ConnectivityState.from_payload(payload)
        if state.thing_name != thing_name:
            LOGGER.warning(
                "Ignoring connectivity state topic/payload mismatch topic=%s payloadThing=%s",
                topic,
                state.thing_name,
            )
            return
        await self.apply_connectivity_state(state)

    async def shutdown(self) -> None:
        for device in list(self._devices.values()):
            if device.mqtt_session is not None:
                await device.mqtt_session.teardown(explicit_death=True)
        await self.publish_node_death()
        await self._cloud_client.disconnect()


async def run_sparkplug_manager(
    *,
    config: BridgeConfig,
    aws_runtime: AwsRuntime,
    bus: LocalPubSub,
    registry_client: AwsThingRegistryClient | None = None,
    cloud_client: AwsShadowClient | None = None,
    inventory_publish_interval: float = DEFAULT_INVENTORY_PUBLISH_INTERVAL,
) -> None:
    registry_client = registry_client or AwsThingRegistryClient(aws_runtime.iot_client())
    try:
        registrations = registry_client.list_rig_things(config.rig_name)
    except ThingGroupNotFoundError:
        LOGGER.warning(
            "Dynamic thing group for rig=%s was not found; starting with no managed devices",
            config.rig_name,
        )
        registrations = []
    cloud_client = cloud_client or AwsShadowClient(config, aws_runtime)
    snapshots = await cloud_client.connect_and_get_initial_snapshots(
        {
            registration.thing_name: registration.capabilities_set
            for registration in registrations
        },
        timeout_seconds=config.aws_connect_timeout,
    )
    manager = SparkplugManager(
        config,
        aws_runtime=aws_runtime,
        bus=bus,
        cloud_client=cloud_client,
    )
    await manager.subscribe_local_state()
    await manager.set_registrations(registrations, snapshots=snapshots)
    await manager.publish_node_birth()
    inventory_task: asyncio.Task[None] | None = None
    if inventory_publish_interval > 0:
        inventory_task = asyncio.create_task(
            _republish_inventory_loop(manager, interval=inventory_publish_interval)
        )
    try:
        while True:
            updates = await cloud_client.wait_for_updates(timeout_seconds=None)
            await manager.apply_cloud_updates(updates)
    except asyncio.CancelledError:
        if inventory_task is not None:
            inventory_task.cancel()
            await asyncio.gather(inventory_task, return_exceptions=True)
        await manager.shutdown()
        raise


async def _republish_inventory_loop(
    manager: SparkplugManager,
    *,
    interval: float,
) -> None:
    while True:
        await asyncio.sleep(interval)
        await manager.publish_inventory()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-sparkplug-manager",
        description="txing Greengrass Sparkplug lifecycle manager",
    )
    parser.add_argument(
        "--rig-name",
        default=_env_text(DEFAULT_RIG_NAME_ENV, DEFAULT_RIG_NAME),
    )
    parser.add_argument(
        "--sparkplug-group-id",
        default=_env_text(DEFAULT_SPARKPLUG_GROUP_ID_ENV, DEFAULT_SPARKPLUG_GROUP_ID),
    )
    parser.add_argument(
        "--sparkplug-edge-node-id",
        default=_env_text(
            DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV,
            DEFAULT_SPARKPLUG_EDGE_NODE_ID,
        ),
    )
    parser.add_argument(
        "--client-id",
        default=None,
    )
    parser.add_argument(
        "--aws-connect-timeout",
        type=float,
        default=DEFAULT_AWS_CONNECT_TIMEOUT,
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if boto3 is None:
        print("rig-sparkplug-manager start failed: boto3 is required", flush=True)
        raise SystemExit(2)
    ensure_aws_profile("AWS_RIG_PROFILE")
    aws_region = resolve_aws_region()
    if not aws_region:
        print("rig-sparkplug-manager start failed: AWS region is not configured", flush=True)
        raise SystemExit(2)
    aws_runtime = build_aws_runtime(region_name=aws_region)
    resolved_edge_node_id = _resolve_sparkplug_edge_node_id(
        rig_name=args.rig_name,
        sparkplug_edge_node_id=args.sparkplug_edge_node_id,
    )
    config = BridgeConfig(
        rig_name=args.rig_name,
        sparkplug_group_id=args.sparkplug_group_id,
        sparkplug_edge_node_id=resolved_edge_node_id,
        iot_endpoint=aws_runtime.iot_data_endpoint(),
        aws_region=aws_region,
        client_id=args.client_id or f"rig-{os.getpid()}-manager",
        aws_connect_timeout=args.aws_connect_timeout,
        reconnect_delay=args.reconnect_delay,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
        manager_task = asyncio.create_task(
            run_sparkplug_manager(
                config=config,
                aws_runtime=aws_runtime,
                bus=GreengrassLocalPubSub(),
            )
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            {manager_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    asyncio.run(_runner())
