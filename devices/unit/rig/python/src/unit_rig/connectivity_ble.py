from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from dataclasses import replace
from pathlib import Path
from typing import Any

from .ble_bridge import (
    DEFAULT_AWS_CONNECT_TIMEOUT,
    DEFAULT_BLE_GATT_UUIDS,
    DEFAULT_LOCK_FILE,
    DEFAULT_NAME_FRAGMENT,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_RIG_NAME,
    DEFAULT_RIG_NAME_ENV,
    AwsShadowUpdate,
    BleGattUuids,
    BleSleepBridge,
    BridgeConfig,
    DeviceCloudProxy,
    InstanceLock,
    ManagedThing,
    RigFleetBridge,
    ShadowState,
    _env_text,
)
from .connectivity_protocol import (
    COMMAND_ACCEPTED,
    COMMAND_FAILED,
    CONTROL_EVENTUAL,
    CONTROL_UNAVAILABLE,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    COMMAND_TOPIC_PREFIX,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityHeartbeat,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    TRANSPORT_BLE_GATT,
    build_command_result_topic,
    build_heartbeat_topic,
    build_state_topic,
    parse_command_topic,
)
from .local_pubsub import GreengrassLocalPubSub, LocalPubSub
from .sparkplug import utc_timestamp_ms
from .thing_registry import ThingRegistration

LOGGER = logging.getLogger("unit_rig.connectivity_ble")
DEFAULT_ADAPTER_ID = "ble-main"


class ConnectivityBleCloudProxy:
    def __init__(
        self,
        *,
        adapter_id: str,
        bus: LocalPubSub,
    ) -> None:
        self._adapter_id = adapter_id
        self._bus = bus
        self._updates: asyncio.Queue[AwsShadowUpdate] = asyncio.Queue()
        self._shadows: dict[str, ShadowState] = {}
        self._seq = 0

    def set_shadow(self, thing_name: str, shadow: ShadowState) -> None:
        self._shadows[thing_name] = shadow

    async def enqueue_command(self, command: ConnectivityCommand) -> None:
        target_redcon = 3 if command.power else 4
        await self._updates.put(
            AwsShadowUpdate(
                thing_name=command.thing_name,
                source="connectivity/command",
                command_redcon=target_redcon,
            )
        )
        await self._publish_command_result(
            ConnectivityCommandResult(
                adapter_id=self._adapter_id,
                command_id=command.command_id,
                thing_name=command.thing_name,
                status=COMMAND_ACCEPTED,
                message=None,
                observed_at_ms=utc_timestamp_ms(),
            )
        )

    def drain_updates(self) -> list[AwsShadowUpdate]:
        updates: list[AwsShadowUpdate] = []
        while True:
            try:
                updates.append(self._updates.get_nowait())
            except asyncio.QueueEmpty:
                return updates

    async def wait_for_updates(
        self,
        timeout_seconds: float | None = None,
    ) -> list[AwsShadowUpdate]:
        if not self._updates.empty():
            return self.drain_updates()
        try:
            if timeout_seconds is None:
                update = await self._updates.get()
            else:
                update = await asyncio.wait_for(
                    self._updates.get(),
                    timeout=timeout_seconds,
                )
        except TimeoutError:
            return []
        updates = [update]
        updates.extend(self.drain_updates())
        return updates

    async def update_shadow(
        self,
        *,
        thing_name: str,
        reported_device_patch: dict[str, Any] | None,
        reported_root_patch: dict[str, Any] | None = None,
        publish_timeout_seconds: float | None = None,
    ) -> None:
        del reported_device_patch, reported_root_patch, publish_timeout_seconds
        await self.publish_state(thing_name)

    async def update_named_shadow_reported(self, **_kwargs: object) -> None:
        return

    async def publish_sparkplug(self, *_args: object, **_kwargs: object) -> None:
        return

    async def disconnect(self) -> None:
        return

    async def publish_state(self, thing_name: str) -> None:
        shadow = self._shadows.get(thing_name)
        if shadow is None:
            return
        self._seq += 1
        state = ConnectivityState(
            adapter_id=self._adapter_id,
            thing_name=thing_name,
            transport=TRANSPORT_BLE_GATT,
            native_identity=(
                {"bleDeviceId": shadow.ble_device_id}
                if shadow.ble_device_id
                else {}
            ),
            presence=PRESENCE_ONLINE if shadow.ble_online else PRESENCE_OFFLINE,
            control_availability=(
                CONTROL_EVENTUAL if shadow.ble_online else CONTROL_UNAVAILABLE
            ),
            power=shadow.reported_power,
            sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
            battery_mv=shadow.battery_mv,
            observed_at_ms=utc_timestamp_ms(),
            seq=self._seq,
        )
        await self._bus.publish(build_state_topic(thing_name), state.to_json())
        LOGGER.info(
            "Published connectivity state thing=%s presence=%s control=%s power=%s bleDeviceId=%s seq=%s",
            thing_name,
            state.presence,
            state.control_availability,
            state.power,
            state.native_identity.get("bleDeviceId"),
            state.seq,
        )

    async def _publish_command_result(self, result: ConnectivityCommandResult) -> None:
        await self._bus.publish(
            build_command_result_topic(result.thing_name),
            result.to_json(),
        )


class ConnectivityBleService:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        bus: LocalPubSub,
        adapter_id: str = DEFAULT_ADAPTER_ID,
        no_ble: bool = False,
    ) -> None:
        self._config = config
        self._bus = bus
        self._adapter_id = adapter_id
        self._no_ble = no_ble
        self._cloud_proxy = ConnectivityBleCloudProxy(
            adapter_id=adapter_id,
            bus=bus,
        )
        self._inventory_event = asyncio.Event()
        self._inventory: ConnectivityInventory | None = None
        self._inventory_signature: tuple[object, ...] | None = None
        self._fleet_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._bus.subscribe(INVENTORY_TOPIC, self._handle_inventory_message)
        await self._bus.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", self._handle_command_message)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while True:
                await self._inventory_event.wait()
                self._inventory_event.clear()
                await self._restart_fleet()
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            if self._fleet_task is not None:
                self._fleet_task.cancel()
                await asyncio.gather(self._fleet_task, return_exceptions=True)

    async def _handle_inventory_message(self, _topic: str, payload: bytes) -> None:
        inventory = ConnectivityInventory.from_payload(payload)
        signature = self._inventory_device_signature(inventory)
        should_restart = (
            self._inventory_signature != signature
            or self._fleet_task is None
            or self._fleet_task.done()
        )
        self._inventory = inventory
        self._inventory_signature = signature
        LOGGER.info(
            "Received connectivity inventory seq=%s devices=%s restart=%s",
            inventory.seq,
            len(inventory.devices),
            should_restart,
        )
        if should_restart:
            self._inventory_event.set()

    @staticmethod
    def _inventory_device_signature(
        inventory: ConnectivityInventory,
    ) -> tuple[object, ...]:
        return tuple(
            (
                device.thing_name,
                device.transport,
                tuple(
                    sorted(
                        (key, repr(value))
                        for key, value in device.native_identity.items()
                    )
                ),
                device.sleep_model,
            )
            for device in inventory.devices
        )

    async def _handle_command_message(self, topic: str, payload: bytes) -> None:
        thing_name = parse_command_topic(topic)
        if thing_name is None:
            return
        try:
            command = ConnectivityCommand.from_payload(payload)
            if command.thing_name != thing_name:
                raise ValueError(
                    f"command topic thing={thing_name} differs from payload thing={command.thing_name}"
                )
            await self._cloud_proxy.enqueue_command(command)
        except Exception as err:
            LOGGER.warning("Invalid connectivity command topic=%s error=%s", topic, err)
            try:
                command = ConnectivityCommand.from_payload(payload)
                await self._bus.publish(
                    build_command_result_topic(command.thing_name),
                    ConnectivityCommandResult(
                        adapter_id=self._adapter_id,
                        command_id=command.command_id,
                        thing_name=command.thing_name,
                        status=COMMAND_FAILED,
                        message=str(err),
                        observed_at_ms=utc_timestamp_ms(),
                    ).to_json(),
                )
            except Exception:
                return

    async def _restart_fleet(self) -> None:
        if self._fleet_task is not None:
            self._fleet_task.cancel()
            await asyncio.gather(self._fleet_task, return_exceptions=True)
            self._fleet_task = None

        inventory = self._inventory
        if inventory is None:
            return
        managed_things = self._build_managed_things(inventory)
        LOGGER.info(
            "Starting BLE fleet for managed things=%s",
            [managed.registration.thing_name for managed in managed_things],
        )
        for managed in managed_things:
            await self._cloud_proxy.publish_state(managed.registration.thing_name)

        fleet = RigFleetBridge(
            self._config,
            cloud_shadow=self._cloud_proxy,  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            managed_things=managed_things,
        )
        self._fleet_task = asyncio.create_task(
            fleet.run_no_ble() if self._no_ble else fleet.run()
        )

    def _build_managed_things(
        self,
        inventory: ConnectivityInventory,
    ) -> list[ManagedThing]:
        managed: list[ManagedThing] = []
        for device in inventory.devices:
            if device.transport != TRANSPORT_BLE_GATT:
                continue
            thing_name = device.thing_name
            ble_device_id = device.native_identity.get("bleDeviceId")
            if not isinstance(ble_device_id, str) or not ble_device_id.strip():
                ble_device_id = None
            ble_uuids = DEFAULT_BLE_GATT_UUIDS.with_device_id(ble_device_id)
            shadow = ShadowState(
                ble_uuids=ble_uuids,
                ble_online=False,
                reported_power=False,
                thing_name=thing_name,
                aws_region=self._config.aws_region,
            )
            self._cloud_proxy.set_shadow(thing_name, shadow)
            device_config = replace(self._config, thing_name=thing_name)
            registration = ThingRegistration(
                thing_name=thing_name,
                thing_type="unit",
                name=thing_name,
                short_id=thing_name,
                town_name=self._config.sparkplug_group_id,
                rig_name=self._config.rig_name,
                capabilities_set=("mcu",),
            )
            managed.append(
                ManagedThing(
                    registration=registration,
                    bridge=BleSleepBridge(
                        device_config,
                        shadow,
                        DeviceCloudProxy(
                            self._cloud_proxy,  # type: ignore[arg-type]
                            thing_name,
                        ),
                    ),
                )
            )
        return managed

    async def _heartbeat_loop(self) -> None:
        seq = 0
        while True:
            seq += 1
            await self._bus.publish(
                build_heartbeat_topic(self._adapter_id),
                ConnectivityHeartbeat(
                    adapter_id=self._adapter_id,
                    status="running",
                    active_thing_name=None,
                    observed_at_ms=utc_timestamp_ms(),
                    seq=seq,
                ).to_json(),
            )
            await asyncio.sleep(10.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="unit-rig-connectivity-ble",
        description="txing Greengrass BLE connectivity adapter",
    )
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--name", default=DEFAULT_NAME_FRAGMENT)
    parser.add_argument("--rig-name", default=_env_text(DEFAULT_RIG_NAME_ENV, DEFAULT_RIG_NAME))
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--reconnect-delay", type=float, default=DEFAULT_RECONNECT_DELAY)
    parser.add_argument("--aws-region", default=os.getenv("AWS_REGION", ""))
    parser.add_argument("--no-ble", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = BridgeConfig(
        name_fragment=args.name,
        rig_name=args.rig_name,
        lock_file=args.lock_file,
        reconnect_delay=args.reconnect_delay,
        aws_connect_timeout=DEFAULT_AWS_CONNECT_TIMEOUT,
        aws_region=args.aws_region,
    )
    lock = InstanceLock(config.lock_file)
    try:
        lock.acquire()
    except RuntimeError as err:
        print(f"unit-rig-connectivity-ble start failed: {err}", flush=True)
        raise SystemExit(2) from err

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
        service_task = asyncio.create_task(
            ConnectivityBleService(
                config,
                bus=GreengrassLocalPubSub(),
                adapter_id=args.adapter_id,
                no_ble=args.no_ble,
            ).start()
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            {service_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    try:
        asyncio.run(_runner())
    finally:
        lock.release()
