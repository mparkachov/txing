from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import struct
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Iterable

try:
    from bleak import BleakClient
    from bleak.exc import BleakError
except ImportError:  # pragma: no cover - startup validation covers real deployments
    BleakClient = None
    BleakError = RuntimeError

from rig.connectivity_protocol import (
    BLE_ADVERTISEMENT_TOPIC_PREFIX,
    BLE_SCAN_CONTROL_TOPIC,
    BLE_SCAN_PAUSE,
    BLE_SCAN_RESUME,
    COMMAND_ACCEPTED,
    COMMAND_FAILED,
    COMMAND_SUCCEEDED,
    COMMAND_TOPIC_PREFIX,
    CONTROL_EVENTUAL,
    CONTROL_UNAVAILABLE,
    INVENTORY_TOPIC,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    BleAdvertisement,
    BleScanControl,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityHeartbeat,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
    build_command_result_topic,
    build_heartbeat_topic,
    build_state_topic,
    parse_ble_advertisement_topic,
    parse_command_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

LOGGER = logging.getLogger("power_rig.connectivity_ble")

DEFAULT_ADAPTER_ID = "power-ble-main"
POWER_INVENTORY_ADAPTER_ID = "power-sparkplug-manager"
DEFAULT_SCAN_TIMEOUT = 8.0
DEFAULT_PRESENCE_TIMEOUT = 20.0
DEFAULT_RECONNECT_DELAY = 2.0
DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_COMMAND_TIMEOUT = 8.0
DEFAULT_HEARTBEAT_INTERVAL = 10.0
DEFAULT_STATE_REPORT_INTERVAL = 0.0
DEFAULT_SCAN_PAUSE_SETTLE = 0.25
DEFAULT_SCAN_PAUSE_MARGIN = 2.0

POWER_SERVICE_UUID = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"
POWER_COMMAND_UUID = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100"
POWER_STATE_UUID = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100"

PROTOCOL_VERSION = 1
REDCON_IDLE = 4
REDCON_ACTIVE = 3

COMMAND_STRUCT = struct.Struct("<BB")
STATE_STRUCT = struct.Struct("<BBH")


@dataclass(slots=True, frozen=True)
class PowerBleConfig:
    adapter_id: str = DEFAULT_ADAPTER_ID
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    presence_timeout: float = DEFAULT_PRESENCE_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL
    state_report_interval: float = DEFAULT_STATE_REPORT_INTERVAL
    no_ble: bool = False


@dataclass(slots=True, frozen=True)
class PowerBleState:
    redcon: int
    battery_mv: int | None = None


@dataclass(slots=True, frozen=True)
class _DiscoveredPowerDevice:
    name: str
    address: str
    seq: int
    details: dict[str, Any]


def normalize_target_redcon(power: bool) -> int:
    return REDCON_ACTIVE if power else REDCON_IDLE


def encode_redcon_command(target_redcon: int) -> bytes:
    if target_redcon in (1, 2):
        target_redcon = REDCON_ACTIVE
    if target_redcon not in (REDCON_ACTIVE, REDCON_IDLE):
        raise ValueError(f"unsupported power target REDCON: {target_redcon}")
    return COMMAND_STRUCT.pack(PROTOCOL_VERSION, target_redcon)


def parse_state_report(data: bytes | bytearray | memoryview) -> PowerBleState:
    payload = bytes(data)
    if len(payload) < STATE_STRUCT.size:
        raise ValueError("power BLE state report is too short")
    version, redcon, battery_mv = STATE_STRUCT.unpack_from(payload)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported power BLE state version: {version}")
    if redcon in (1, 2):
        redcon = REDCON_ACTIVE
    if redcon not in (REDCON_ACTIVE, REDCON_IDLE):
        raise ValueError(f"unsupported power BLE state REDCON: {redcon}")
    return PowerBleState(redcon=redcon, battery_mv=battery_mv or None)


def _command_deadline_expired(command: ConnectivityCommand) -> bool:
    return command.deadline_ms is not None and utc_timestamp_ms() >= command.deadline_ms


def _command_deadline_expired_message(
    command: ConnectivityCommand,
    *,
    last_connect_error: str | None = None,
) -> str:
    if last_connect_error:
        return (
            "power BLE command deadline expired after connection failures: "
            f"{last_connect_error} deadlineMs={command.deadline_ms}"
        )
    return f"power BLE command deadline expired deadlineMs={command.deadline_ms}"


def _connect_failed_message(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return f"power BLE connection failed before command write: {message}"


class PowerBleDeviceSession:
    def __init__(
        self,
        *,
        thing_name: str,
        config: PowerBleConfig,
        bus: LocalPubSub,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.thing_name = thing_name
        self._config = config
        self._bus = bus
        self._client_factory = client_factory or _default_client
        self._command_queue: asyncio.Queue[ConnectivityCommand] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._advertisement_event = asyncio.Event()
        self._seq = 0
        self._last_state = PowerBleState(redcon=REDCON_IDLE)
        self._ble_address: str | None = None
        self._last_advertisement: BleAdvertisement | None = None
        self._last_connect_error_message: str | None = None
        self._connect_attempt_advertisement_seq: int | None = None
        self._ble_connected = False

    def stop(self) -> None:
        self._stop_event.set()
        self._advertisement_event.set()

    async def enqueue_command(self, command: ConnectivityCommand) -> None:
        if _command_deadline_expired(command):
            await self._publish_command_result(
                command,
                status=COMMAND_FAILED,
                message=_command_deadline_expired_message(command),
            )
            return
        if self._command_queue.empty():
            self._last_connect_error_message = None
        await self._command_queue.put(command)
        self._advertisement_event.set()

    def observe_advertisement(self, advertisement: BleAdvertisement) -> None:
        if not _advertisement_matches_power_device(advertisement, self.thing_name):
            return
        previous_address = (
            self._last_advertisement.address if self._last_advertisement else None
        )
        if previous_address != advertisement.address:
            LOGGER.info(
                "Observed power BLE advertisement thing=%s address=%s name=%s rssi=%s",
                self.thing_name,
                advertisement.address,
                advertisement.name or "-",
                advertisement.rssi,
            )
        self._last_advertisement = advertisement
        self._ble_address = advertisement.address
        self._advertisement_event.set()

    async def run(self) -> None:
        if self._config.no_ble:
            await self._publish_connectivity(
                presence=PRESENCE_OFFLINE,
                control_availability=CONTROL_UNAVAILABLE,
                power=False,
                battery_mv=None,
                ble_connected=False,
            )
            await self._stop_event.wait()
            return

        while not self._stop_event.is_set():
            await self._fail_expired_queued_commands()
            try:
                device = await self._discover_device()
                if device is None:
                    await self._publish_connectivity(
                        presence=PRESENCE_OFFLINE,
                        control_availability=CONTROL_UNAVAILABLE,
                        power=False,
                        battery_mv=self._last_state.battery_mv,
                        ble_connected=False,
                    )
                    await _sleep_until_stop(self._stop_event, self._config.reconnect_delay)
                    continue
                should_connect = await self._run_advertising_presence(device)
                if should_connect:
                    await self._run_connected(device)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if _is_transient_ble_error(err):
                    LOGGER.warning(
                        "Power BLE session failed thing=%s error=%s; retrying in %.1f seconds: %s",
                        self.thing_name,
                        type(err).__name__,
                        self._config.reconnect_delay,
                        err,
                    )
                else:
                    LOGGER.exception(
                        "Power BLE session failed thing=%s error=%s; retrying in %.1f seconds",
                        self.thing_name,
                        type(err).__name__,
                        self._config.reconnect_delay,
                    )
                connect_failed_message = _connect_failed_message(err)
                if _should_retry_connection_error(err):
                    self._last_connect_error_message = connect_failed_message
                    self._discard_failed_connect_advertisement()
                else:
                    await self._fail_queued_commands(connect_failed_message)
                await self._fail_expired_queued_commands()
                await _sleep_until_stop(self._stop_event, self._config.reconnect_delay)

    async def _run_advertising_presence(self, device: Any) -> bool:
        self._ble_address = _device_address(device)
        LOGGER.info(
            "Power BLE advertisement is fresh thing=%s address=%s",
            self.thing_name,
            self._ble_address or "-",
        )
        await self._publish_state_report(self._last_state, ble_connected=False)
        return not self._stop_event.is_set()

    async def _discover_device(self) -> Any | None:
        deadline = asyncio.get_running_loop().time() + self._config.scan_timeout
        while not self._stop_event.is_set():
            advertisement = self._last_advertisement
            if self._last_advertisement_is_fresh():
                assert advertisement is not None
                self._ble_address = advertisement.address
                return _DiscoveredPowerDevice(
                    name=self.thing_name,
                    address=advertisement.address,
                    seq=advertisement.seq,
                    details={"local_name": advertisement.name},
                )

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                LOGGER.info(
                    "No fresh power BLE advertisement thing=%s timeout=%.1fs",
                    self.thing_name,
                    self._config.scan_timeout,
                )
                return None
            self._advertisement_event.clear()
            try:
                await asyncio.wait_for(self._advertisement_event.wait(), timeout=remaining)
            except TimeoutError:
                return None
        return None

    def _last_advertisement_is_fresh(self) -> bool:
        advertisement = self._last_advertisement
        return advertisement is not None and _advertisement_is_fresh(
            advertisement,
            max_age_ms=max(int(self._config.scan_timeout * 1000), 1000),
        )

    async def _run_connected(self, device: Any) -> None:
        client = self._create_client(device)
        connected = False
        scan_paused = False
        self._connect_attempt_advertisement_seq = _device_seq(device)
        try:
            await self._publish_scan_control(
                action=BLE_SCAN_PAUSE,
                reason=f"connect:{self.thing_name}",
                deadline_ms=utc_timestamp_ms()
                + int(
                    (
                        self._config.connect_timeout
                        + self._config.command_timeout
                        + DEFAULT_SCAN_PAUSE_MARGIN
                    )
                    * 1000
                ),
            )
            scan_paused = True
            await _sleep_until_stop(self._stop_event, DEFAULT_SCAN_PAUSE_SETTLE)
            LOGGER.info(
                "Connecting power BLE thing=%s address=%s timeout=%.1fs",
                self.thing_name,
                _device_address(device) or "-",
                self._config.connect_timeout,
            )
            await _client_connect(client, timeout=self._config.connect_timeout)
            connected = True
            self._ble_connected = True
            self._ble_address = _device_address(device)
            await _ensure_client_services(client, timeout=self._config.command_timeout)
            self._connect_attempt_advertisement_seq = None
            await self._start_notifications(client)
            await self._drain_ready_commands(client)
            await self._publish_scan_control(
                action=BLE_SCAN_RESUME,
                reason=f"connected:{self.thing_name}",
                deadline_ms=None,
            )
            scan_paused = False
            state_report_interval = self._config.state_report_interval
            next_state_report_at = (
                asyncio.get_running_loop().time() + state_report_interval
                if state_report_interval > 0
                else None
            )
            while not self._stop_event.is_set() and _client_is_connected(client):
                if next_state_report_at is None:
                    timeout = 1.0
                else:
                    now = asyncio.get_running_loop().time()
                    if now >= next_state_report_at:
                        await self._publish_state_report(
                            self._last_state,
                            ble_connected=True,
                        )
                        next_state_report_at = now + state_report_interval
                        continue
                    timeout = min(1.0, next_state_report_at - now)
                try:
                    command = await asyncio.wait_for(self._command_queue.get(), timeout=timeout)
                except TimeoutError:
                    continue
                if _command_deadline_expired(command):
                    await self._publish_command_result(
                        command,
                        status=COMMAND_FAILED,
                        message=_command_deadline_expired_message(
                            command,
                            last_connect_error=self._last_connect_error_message,
                        ),
                    )
                    continue
                await self._execute_command(client, command)
                if next_state_report_at is not None:
                    next_state_report_at = asyncio.get_running_loop().time() + state_report_interval
        finally:
            self._ble_connected = False
            if scan_paused:
                await self._publish_scan_control(
                    action=BLE_SCAN_RESUME,
                    reason=f"connect-finished:{self.thing_name}",
                    deadline_ms=None,
                )
            if connected:
                await _client_disconnect(client)
            else:
                await _cleanup_client_after_failed_connect(client)

    def _create_client(self, device: Any) -> Any:
        if self._client_factory is _default_client:
            return _default_client(device, timeout=self._config.connect_timeout)
        return self._client_factory(device)

    def _discard_failed_connect_advertisement(self) -> None:
        attempted_seq = self._connect_attempt_advertisement_seq
        self._connect_attempt_advertisement_seq = None
        advertisement = self._last_advertisement
        if attempted_seq is not None and advertisement is not None and advertisement.seq == attempted_seq:
            self._last_advertisement = None
            self._advertisement_event.clear()

    async def _start_notifications(self, client: Any) -> None:
        try:
            state_payload = await client.read_gatt_char(POWER_STATE_UUID)
        except Exception:
            LOGGER.debug("Power BLE state read failed thing=%s", self.thing_name, exc_info=True)
        else:
            await self._handle_state_bytes(state_payload)

        loop = asyncio.get_running_loop()

        def state_handler(_sender: object, payload: bytes | bytearray) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_state_bytes(payload))
            )

        try:
            await client.start_notify(POWER_STATE_UUID, state_handler)
        except Exception:
            LOGGER.debug(
                "Power BLE notification setup failed thing=%s uuid=%s",
                self.thing_name,
                POWER_STATE_UUID,
                exc_info=True,
            )

    async def _execute_command(self, client: Any, command: ConnectivityCommand) -> None:
        target_redcon = normalize_target_redcon(command.power)
        LOGGER.info(
            "Writing power BLE command thing=%s commandId=%s targetRedcon=%s timeout=%.1fs",
            self.thing_name,
            command.command_id,
            target_redcon,
            self._config.command_timeout,
        )
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    POWER_COMMAND_UUID,
                    encode_redcon_command(target_redcon),
                    response=True,
                ),
                timeout=self._config.command_timeout,
            )
        except Exception as err:
            message = str(err) or type(err).__name__
            if _should_retry_connection_error(err):
                self._last_connect_error_message = _connect_failed_message(err)
                if (
                    self._connect_attempt_advertisement_seq is None
                    and self._last_advertisement is not None
                ):
                    self._connect_attempt_advertisement_seq = self._last_advertisement.seq
                await self._command_queue.put(command)
                raise
            await self._publish_command_result(command, status=COMMAND_FAILED, message=message)
            return
        self._last_state = PowerBleState(
            redcon=target_redcon,
            battery_mv=self._last_state.battery_mv,
        )
        self._last_connect_error_message = None
        await self._publish_state_report(self._last_state, ble_connected=True)
        await self._publish_command_result(command, status=COMMAND_SUCCEEDED, message=None)

    async def _drain_ready_commands(self, client: Any) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if _command_deadline_expired(command):
                await self._publish_command_result(
                    command,
                    status=COMMAND_FAILED,
                    message=_command_deadline_expired_message(
                        command,
                        last_connect_error=self._last_connect_error_message,
                    ),
                )
                continue
            await self._execute_command(client, command)

    async def _fail_queued_commands(self, message: str) -> None:
        failed_any = False
        while True:
            try:
                command = self._command_queue.get_nowait()
            except asyncio.QueueEmpty:
                if failed_any:
                    self._last_connect_error_message = None
                return
            failed_any = True
            await self._publish_command_result(command, status=COMMAND_FAILED, message=message)

    async def _fail_expired_queued_commands(self) -> None:
        pending: list[ConnectivityCommand] = []
        failed_any = False
        while True:
            try:
                command = self._command_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if _command_deadline_expired(command):
                failed_any = True
                await self._publish_command_result(
                    command,
                    status=COMMAND_FAILED,
                    message=_command_deadline_expired_message(
                        command,
                        last_connect_error=self._last_connect_error_message,
                    ),
                )
            else:
                pending.append(command)
        for command in pending:
            await self._command_queue.put(command)
        if failed_any and not pending:
            self._last_connect_error_message = None

    async def _publish_scan_control(
        self,
        *,
        action: str,
        reason: str,
        deadline_ms: int | None,
    ) -> None:
        await self._bus.publish(
            BLE_SCAN_CONTROL_TOPIC,
            BleScanControl(
                adapter_id=self._config.adapter_id,
                action=action,
                reason=reason,
                observed_at_ms=utc_timestamp_ms(),
                deadline_ms=deadline_ms,
            ).to_json(),
        )

    async def _handle_state_bytes(self, payload: bytes | bytearray | memoryview) -> None:
        try:
            state = parse_state_report(payload)
        except ValueError:
            LOGGER.warning("Ignoring invalid power BLE state thing=%s", self.thing_name, exc_info=True)
            return
        await self._publish_state_report(state, ble_connected=self._ble_connected)

    async def _publish_state_report(self, state: PowerBleState, *, ble_connected: bool) -> None:
        self._last_state = state
        await self._publish_connectivity(
            presence=PRESENCE_ONLINE,
            control_availability=CONTROL_EVENTUAL,
            power=state.redcon < REDCON_IDLE,
            battery_mv=state.battery_mv,
            ble_connected=ble_connected,
        )

    async def _publish_connectivity(
        self,
        *,
        presence: str,
        control_availability: str,
        power: bool,
        battery_mv: int | None,
        ble_connected: bool,
    ) -> None:
        self._seq += 1
        native_identity: dict[str, Any] = {
            "bleLocalName": self.thing_name,
            "bleConnected": ble_connected,
        }
        if self._ble_address:
            native_identity["bleAddress"] = self._ble_address
        state = ConnectivityState(
            adapter_id=self._config.adapter_id,
            thing_name=self.thing_name,
            transport=TRANSPORT_BLE_GATT,
            native_identity=native_identity,
            presence=presence,
            control_availability=control_availability,
            power=power,
            sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
            battery_mv=battery_mv,
            observed_at_ms=utc_timestamp_ms(),
            seq=self._seq,
            weather=None,
        )
        await self._bus.publish(build_state_topic(self.thing_name), state.to_json())

    async def _publish_command_result(
        self,
        command: ConnectivityCommand,
        *,
        status: str,
        message: str | None,
    ) -> None:
        await self._bus.publish(
            build_command_result_topic(command.thing_name),
            ConnectivityCommandResult(
                adapter_id=self._config.adapter_id,
                command_id=command.command_id,
                thing_name=command.thing_name,
                status=status,
                message=message,
                observed_at_ms=utc_timestamp_ms(),
                seq=command.seq,
            ).to_json(),
        )


class PowerConnectivityBleService:
    def __init__(
        self,
        config: PowerBleConfig,
        *,
        bus: LocalPubSub,
        session_factory: Callable[..., PowerBleDeviceSession] = PowerBleDeviceSession,
    ) -> None:
        self._config = config
        self._bus = bus
        self._session_factory = session_factory
        self._sessions: dict[str, PowerBleDeviceSession] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._known_thing_names: set[str] = set()
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()
        for session in self._sessions.values():
            session.stop()

    async def start(self) -> None:
        subscriptions: list[object] = []
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            subscriptions.append(await self._bus.subscribe(INVENTORY_TOPIC, self._handle_inventory))
            subscriptions.append(await self._bus.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", self._handle_command))
            subscriptions.append(
                await self._bus.subscribe(
                    f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                    self._handle_ble_advertisement,
                )
            )
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._stop_event.wait()
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            await self._stop_all_sessions()
            for subscription in subscriptions:
                _close_resource(subscription)

    async def _handle_inventory(self, _topic: str, payload: bytes) -> None:
        inventory = ConnectivityInventory.from_payload(payload)
        if inventory.adapter_id != POWER_INVENTORY_ADAPTER_ID:
            return
        wanted = tuple(
            device.thing_name
            for device in inventory.devices
            if device.transport == TRANSPORT_BLE_GATT
            and device.sleep_model == SLEEP_MODEL_BLE_CONNECTED_IDLE
        )
        self._known_thing_names = set(wanted)
        await self._reconcile_sessions(wanted)

    async def _reconcile_sessions(self, wanted: Iterable[str]) -> None:
        wanted_set = set(wanted)
        for thing_name in sorted(set(self._sessions) - wanted_set):
            session = self._sessions.pop(thing_name)
            session.stop()
            task = self._tasks.pop(thing_name)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        for thing_name in sorted(wanted_set - set(self._sessions)):
            session = self._session_factory(
                thing_name=thing_name,
                config=self._config,
                bus=self._bus,
            )
            self._sessions[thing_name] = session
            self._tasks[thing_name] = asyncio.create_task(session.run())

    async def _handle_ble_advertisement(self, topic: str, payload: bytes) -> None:
        if parse_ble_advertisement_topic(topic) is None:
            return
        try:
            advertisement = BleAdvertisement.from_payload(payload)
        except Exception as err:
            LOGGER.warning("Invalid shared BLE advertisement topic=%s error=%s", topic, err)
            return
        for session in self._sessions.values():
            session.observe_advertisement(advertisement)

    async def _handle_command(self, topic: str, payload: bytes) -> None:
        thing_name = parse_command_topic(topic)
        if thing_name is None:
            return
        try:
            command = ConnectivityCommand.from_payload(payload)
            if command.thing_name != thing_name:
                raise ValueError(
                    f"command topic thing={thing_name} differs from payload thing={command.thing_name}"
                )
            if command.thing_name not in self._known_thing_names:
                return
            session = self._sessions.get(thing_name)
            if session is None:
                raise RuntimeError(f"power BLE thing {thing_name!r} is not in inventory")
            if _command_deadline_expired(command):
                await self._publish_command_result(
                    command,
                    status=COMMAND_FAILED,
                    message=_command_deadline_expired_message(command),
                )
                return
            await self._publish_command_result(command, status=COMMAND_ACCEPTED, message=None)
            await session.enqueue_command(command)
        except Exception as err:
            LOGGER.warning("Invalid power BLE command topic=%s error=%s", topic, err)
            try:
                command = ConnectivityCommand.from_payload(payload)
            except Exception:
                return
            await self._publish_command_result(command, status=COMMAND_FAILED, message=str(err))

    async def _publish_command_result(
        self,
        command: ConnectivityCommand,
        *,
        status: str,
        message: str | None,
    ) -> None:
        await self._bus.publish(
            build_command_result_topic(command.thing_name),
            ConnectivityCommandResult(
                adapter_id=self._config.adapter_id,
                command_id=command.command_id,
                thing_name=command.thing_name,
                status=status,
                message=message,
                observed_at_ms=utc_timestamp_ms(),
                seq=command.seq,
            ).to_json(),
        )

    async def _heartbeat_loop(self) -> None:
        seq = 0
        while True:
            seq += 1
            await self._bus.publish(
                build_heartbeat_topic(self._config.adapter_id),
                ConnectivityHeartbeat(
                    adapter_id=self._config.adapter_id,
                    status="running",
                    active_thing_name=None,
                    observed_at_ms=utc_timestamp_ms(),
                    seq=seq,
                ).to_json(),
            )
            await asyncio.sleep(self._config.heartbeat_interval)

    async def _stop_all_sessions(self) -> None:
        for session in self._sessions.values():
            session.stop()
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._sessions.clear()
        self._tasks.clear()


def _default_client(device: Any, *, timeout: float = DEFAULT_CONNECT_TIMEOUT) -> Any:
    if BleakClient is None:
        raise RuntimeError("bleak is required for power BLE connectivity")
    return BleakClient(_device_address(device) or device, timeout=timeout)


async def _client_connect(client: Any, *, timeout: float) -> None:
    connect = getattr(client, "connect", None)
    if callable(connect):
        await asyncio.wait_for(connect(), timeout=timeout)
        return
    enter = getattr(client, "__aenter__", None)
    if callable(enter):
        await asyncio.wait_for(enter(), timeout=timeout)


async def _ensure_client_services(client: Any, *, timeout: float) -> None:
    try:
        getattr(client, "services")
        return
    except AttributeError:
        pass
    except Exception as err:
        if not _is_service_discovery_missing_error(err):
            raise

    get_services = getattr(client, "get_services", None)
    if not callable(get_services):
        return

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        result = get_services()
    if hasattr(result, "__await__"):
        await asyncio.wait_for(result, timeout=timeout)


async def _client_disconnect(client: Any) -> None:
    disconnect = getattr(client, "disconnect", None)
    if callable(disconnect):
        result = disconnect()
        if hasattr(result, "__await__"):
            await result
        return
    exit_method = getattr(client, "__aexit__", None)
    if callable(exit_method):
        await exit_method(None, None, None)


def _client_is_connected(client: Any) -> bool:
    backend = getattr(client, "_backend", None)
    if backend is not None:
        backend_value = getattr(backend, "is_connected", None)
        if backend_value is not None and not callable(backend_value):
            return bool(backend_value)
    value = getattr(client, "is_connected", True)
    if callable(value):
        return True
    return bool(value)


async def _cleanup_client_after_failed_connect(client: Any) -> None:
    if not _client_is_connected(client):
        return
    try:
        await asyncio.wait_for(_client_disconnect(client), timeout=5.0)
    except Exception:
        LOGGER.debug("Power BLE cleanup after failed connect failed", exc_info=True)


def _is_transient_ble_error(err: Exception) -> bool:
    return isinstance(err, (TimeoutError, BleakError))


def _should_retry_connection_error(err: Exception) -> bool:
    if isinstance(err, TimeoutError):
        return True
    if not isinstance(err, BleakError):
        return False
    message = str(err).lower()
    return (
        "failed to discover services" in message
        or "device disconnected" in message
        or _is_service_discovery_missing_error(err)
    )


def _is_service_discovery_missing_error(err: Exception) -> bool:
    return "service discovery has not been performed yet" in str(err).lower()


def _device_address(device: Any) -> str | None:
    address = getattr(device, "address", None)
    return address if isinstance(address, str) and address.strip() else None


def _device_seq(device: Any) -> int | None:
    seq = getattr(device, "seq", None)
    return seq if isinstance(seq, int) else None


def _advertisement_matches_power_device(
    advertisement: BleAdvertisement,
    thing_name: str,
) -> bool:
    return advertisement.name == thing_name


def _advertisement_is_fresh(
    advertisement: BleAdvertisement,
    *,
    max_age_ms: int,
) -> bool:
    return utc_timestamp_ms() - advertisement.observed_at_ms <= max_age_ms


async def _sleep_until_stop(stop_event: asyncio.Event, delay: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
    except TimeoutError:
        return


def _close_resource(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="power-rig-connectivity-ble",
        description="txing power BLE connected-idle adapter",
    )
    parser.add_argument("--adapter-id", default=os.getenv("POWER_BLE_ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--scan-timeout", type=float, default=float(os.getenv("POWER_BLE_SCAN_TIMEOUT", DEFAULT_SCAN_TIMEOUT)))
    parser.add_argument("--presence-timeout", type=float, default=float(os.getenv("POWER_BLE_PRESENCE_TIMEOUT", DEFAULT_PRESENCE_TIMEOUT)))
    parser.add_argument("--reconnect-delay", type=float, default=float(os.getenv("POWER_BLE_RECONNECT_DELAY", DEFAULT_RECONNECT_DELAY)))
    parser.add_argument("--connect-timeout", type=float, default=float(os.getenv("POWER_BLE_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT)))
    parser.add_argument("--command-timeout", type=float, default=float(os.getenv("POWER_BLE_COMMAND_TIMEOUT", DEFAULT_COMMAND_TIMEOUT)))
    parser.add_argument("--state-report-interval", type=float, default=float(os.getenv("POWER_BLE_STATE_REPORT_INTERVAL", DEFAULT_STATE_REPORT_INTERVAL)))
    parser.add_argument("--no-ble", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = PowerBleConfig(
        adapter_id=args.adapter_id,
        scan_timeout=args.scan_timeout,
        presence_timeout=args.presence_timeout,
        reconnect_delay=args.reconnect_delay,
        connect_timeout=args.connect_timeout,
        command_timeout=args.command_timeout,
        state_report_interval=args.state_report_interval,
        no_ble=args.no_ble,
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
        bus = GreengrassLocalPubSub()
        service = PowerConnectivityBleService(config, bus=bus)
        service_task: asyncio.Task[None] | None = None
        shutdown_task: asyncio.Task[bool] | None = None
        try:
            service_task = asyncio.create_task(service.start())
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, pending = await asyncio.wait(
                {service_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done and not service_task.done():
                service.stop()
                await service_task
            else:
                service_task.result()
            for task in pending:
                if task is not service_task:
                    task.cancel()
            await asyncio.gather(
                *(task for task in pending if task is not service_task),
                return_exceptions=True,
            )
        finally:
            service.stop()
            if service_task is not None and not service_task.done():
                service_task.cancel()
                await asyncio.gather(service_task, return_exceptions=True)
            if shutdown_task is not None and not shutdown_task.done():
                shutdown_task.cancel()
                await asyncio.gather(shutdown_task, return_exceptions=True)
            bus.close()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
