from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import struct
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
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityHeartbeat,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
    WeatherMeasurements,
    build_command_result_topic,
    build_heartbeat_topic,
    build_state_topic,
    parse_ble_advertisement_topic,
    parse_command_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

LOGGER = logging.getLogger("weather_rig.connectivity_ble")

DEFAULT_ADAPTER_ID = "weather-ble-main"
WEATHER_INVENTORY_ADAPTER_ID = "weather-sparkplug-manager"
DEFAULT_SCAN_TIMEOUT = 8.0
DEFAULT_RECONNECT_DELAY = 2.0
DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_COMMAND_TIMEOUT = 8.0
DEFAULT_HEARTBEAT_INTERVAL = 10.0
DEFAULT_STATE_REPORT_INTERVAL = 30.0

WEATHER_SERVICE_UUID = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_COMMAND_UUID = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_STATE_UUID = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_MEASUREMENT_UUID = "f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100"

PROTOCOL_VERSION = 1
REDCON_IDLE = 4
REDCON_ACTIVE = 3
STATE_FLAG_ACTIVE = 0x01
STATE_FLAG_BME280_VALID = 0x02

COMMAND_STRUCT = struct.Struct("<BB")
STATE_STRUCT = struct.Struct("<BBBH")
MEASUREMENT_STRUCT = struct.Struct("<BiIHH")


@dataclass(slots=True, frozen=True)
class WeatherBleConfig:
    adapter_id: str = DEFAULT_ADAPTER_ID
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL
    state_report_interval: float = DEFAULT_STATE_REPORT_INTERVAL
    no_ble: bool = False


@dataclass(slots=True, frozen=True)
class WeatherBleState:
    redcon: int
    battery_mv: int | None = None
    bme280_valid: bool = False


@dataclass(slots=True, frozen=True)
class WeatherBleMeasurement:
    measured_temperature: float
    measured_pressure: float
    measured_humidity: float
    battery_mv: int | None = None


@dataclass(slots=True, frozen=True)
class _DiscoveredWeatherDevice:
    name: str
    address: str
    details: dict[str, Any]


def normalize_target_redcon(power: bool) -> int:
    return REDCON_ACTIVE if power else REDCON_IDLE


def encode_redcon_command(target_redcon: int) -> bytes:
    if target_redcon in (1, 2):
        target_redcon = REDCON_ACTIVE
    if target_redcon not in (REDCON_ACTIVE, REDCON_IDLE):
        raise ValueError(f"unsupported weather target REDCON: {target_redcon}")
    return COMMAND_STRUCT.pack(PROTOCOL_VERSION, target_redcon)


def parse_state_report(data: bytes | bytearray | memoryview) -> WeatherBleState:
    payload = bytes(data)
    if len(payload) < STATE_STRUCT.size:
        raise ValueError("weather BLE state report is too short")
    version, redcon, flags, battery_mv = STATE_STRUCT.unpack_from(payload)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported weather BLE state version: {version}")
    if redcon in (1, 2):
        redcon = REDCON_ACTIVE
    if redcon not in (REDCON_ACTIVE, REDCON_IDLE):
        raise ValueError(f"unsupported weather BLE state REDCON: {redcon}")
    return WeatherBleState(
        redcon=redcon,
        battery_mv=battery_mv or None,
        bme280_valid=bool(flags & STATE_FLAG_BME280_VALID),
    )


def parse_measurement_report(data: bytes | bytearray | memoryview) -> WeatherBleMeasurement:
    payload = bytes(data)
    if len(payload) < MEASUREMENT_STRUCT.size:
        raise ValueError("weather BLE measurement report is too short")
    version, temperature_centi, pressure_pa, humidity_centi, battery_mv = (
        MEASUREMENT_STRUCT.unpack_from(payload)
    )
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported weather BLE measurement version: {version}")
    return WeatherBleMeasurement(
        measured_temperature=temperature_centi / 100.0,
        measured_pressure=pressure_pa / 1000.0,
        measured_humidity=humidity_centi / 100.0,
        battery_mv=battery_mv or None,
    )


class WeatherBleDeviceSession:
    def __init__(
        self,
        *,
        thing_name: str,
        config: WeatherBleConfig,
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
        self._last_state = WeatherBleState(redcon=REDCON_IDLE)
        self._ble_address: str | None = None
        self._last_advertisement: BleAdvertisement | None = None

    def stop(self) -> None:
        self._stop_event.set()
        self._advertisement_event.set()

    async def enqueue_command(self, command: ConnectivityCommand) -> None:
        await self._command_queue.put(command)

    def observe_advertisement(self, advertisement: BleAdvertisement) -> None:
        if not _advertisement_matches_weather_device(advertisement, self.thing_name):
            return
        previous_address = (
            self._last_advertisement.address if self._last_advertisement else None
        )
        if previous_address != advertisement.address:
            LOGGER.info(
                "Observed weather BLE advertisement thing=%s address=%s name=%s rssi=%s",
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
                weather=None,
                battery_mv=None,
            )
            await self._stop_event.wait()
            return

        while not self._stop_event.is_set():
            try:
                device = await self._discover_device()
                if device is None:
                    await self._publish_connectivity(
                        presence=PRESENCE_OFFLINE,
                        control_availability=CONTROL_UNAVAILABLE,
                        power=False,
                        weather=None,
                        battery_mv=None,
                    )
                    await _sleep_until_stop(self._stop_event, self._config.reconnect_delay)
                    continue
                await self._publish_state_report(self._last_state)
                await self._run_connected(device)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                message = (
                    "Weather BLE session failed thing=%s error=%s; retrying in %.1f seconds"
                )
                if _is_transient_ble_error(err):
                    LOGGER.warning(
                        message + ": %s",
                        self.thing_name,
                        type(err).__name__,
                        self._config.reconnect_delay,
                        err,
                    )
                else:
                    LOGGER.exception(
                        message,
                        self.thing_name,
                        type(err).__name__,
                        self._config.reconnect_delay,
                    )
                if not self._last_advertisement_is_fresh():
                    await self._publish_connectivity(
                        presence=PRESENCE_OFFLINE,
                        control_availability=CONTROL_UNAVAILABLE,
                        power=False,
                        weather=None,
                        battery_mv=None,
                    )
                await _sleep_until_stop(self._stop_event, self._config.reconnect_delay)

    async def _run_advertising_presence(self, device: Any) -> None:
        self._ble_address = _device_address(device)
        last_reported_adv_seq = self._last_advertisement.seq if self._last_advertisement else None
        LOGGER.info(
            "Weather BLE advertisement is fresh thing=%s address=%s",
            self.thing_name,
            self._ble_address or "-",
        )
        await self._publish_state_report(self._last_state)

        while not self._stop_event.is_set():
            await self._fail_queued_commands(
                "weather advertising-only firmware does not support BLE commands"
            )
            advertisement = self._last_advertisement
            if advertisement is None or not _advertisement_is_fresh(
                advertisement,
                max_age_ms=max(int(self._config.scan_timeout * 1000), 1000),
            ):
                LOGGER.info(
                    "Weather BLE advertisement expired thing=%s timeout=%.1fs lastAddress=%s lastName=%s",
                    self.thing_name,
                    self._config.scan_timeout,
                    advertisement.address if advertisement else "-",
                    advertisement.name if advertisement else "-",
                )
                await self._publish_connectivity(
                    presence=PRESENCE_OFFLINE,
                    control_availability=CONTROL_UNAVAILABLE,
                    power=False,
                    weather=None,
                    battery_mv=self._last_state.battery_mv,
                )
                return
            if advertisement.seq != last_reported_adv_seq:
                last_reported_adv_seq = advertisement.seq
                await self._publish_state_report(self._last_state)
            self._advertisement_event.clear()
            try:
                await asyncio.wait_for(
                    self._advertisement_event.wait(),
                    timeout=min(max(self._config.scan_timeout, 0.1), 1.0),
                )
            except TimeoutError:
                continue

    async def _fail_queued_commands(self, message: str) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await self._publish_command_result(command, status=COMMAND_FAILED, message=message)

    async def _discover_device(self) -> Any | None:
        deadline = asyncio.get_running_loop().time() + self._config.scan_timeout
        while not self._stop_event.is_set():
            advertisement = self._last_advertisement
            if self._last_advertisement_is_fresh():
                assert advertisement is not None
                self._ble_address = advertisement.address
                return _DiscoveredWeatherDevice(
                    name=self.thing_name,
                    address=advertisement.address,
                    details={"local_name": advertisement.name},
                )

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self._log_no_fresh_advertisement()
                return None
            self._advertisement_event.clear()
            try:
                await asyncio.wait_for(self._advertisement_event.wait(), timeout=remaining)
            except TimeoutError:
                self._log_no_fresh_advertisement()
                return None
        return None

    def _log_no_fresh_advertisement(self) -> None:
        LOGGER.info(
            "No fresh weather BLE advertisement thing=%s timeout=%.1fs lastAddress=%s lastName=%s",
            self.thing_name,
            self._config.scan_timeout,
            self._last_advertisement.address if self._last_advertisement else "-",
            self._last_advertisement.name if self._last_advertisement else "-",
        )

    def _last_advertisement_is_fresh(self) -> bool:
        advertisement = self._last_advertisement
        return advertisement is not None and _advertisement_is_fresh(
            advertisement,
            max_age_ms=max(int(self._config.scan_timeout * 1000), 1000),
        )

    async def _run_connected(self, device: Any) -> None:
        client = self._create_client(device)
        connected = False
        try:
            LOGGER.info(
                "Connecting weather BLE thing=%s address=%s",
                self.thing_name,
                _device_address(device) or "-",
            )
            await _client_connect(client, timeout=self._config.connect_timeout)
            connected = True
            self._ble_address = _device_address(device)
            LOGGER.info(
                "Connected weather BLE thing=%s address=%s",
                self.thing_name,
                self._ble_address or "-",
            )
            await self._publish_state_report(self._last_state)
            await self._start_notifications(client)
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
                        await self._publish_state_report(self._last_state)
                        next_state_report_at = now + state_report_interval
                        continue
                    timeout = min(1.0, next_state_report_at - now)
                try:
                    command = await asyncio.wait_for(self._command_queue.get(), timeout=timeout)
                except TimeoutError:
                    continue
                await self._execute_command(client, command)
                if next_state_report_at is not None:
                    next_state_report_at = asyncio.get_running_loop().time() + state_report_interval
        finally:
            if connected:
                await _client_disconnect(client)
            else:
                await _cleanup_client_after_failed_connect(client)

    def _create_client(self, device: Any) -> Any:
        if self._client_factory is _default_client:
            return _default_client(device, timeout=self._config.connect_timeout)
        return self._client_factory(device)

    async def _start_notifications(self, client: Any) -> None:
        try:
            state_payload = await client.read_gatt_char(WEATHER_STATE_UUID)
        except Exception:
            LOGGER.debug("Weather BLE state read failed thing=%s", self.thing_name, exc_info=True)
        else:
            await self._handle_state_bytes(state_payload)

        loop = asyncio.get_running_loop()

        def state_handler(_sender: object, payload: bytes | bytearray) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_state_bytes(payload))
            )

        def measurement_handler(_sender: object, payload: bytes | bytearray) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_measurement_bytes(payload))
            )

        for uuid, handler in (
            (WEATHER_STATE_UUID, state_handler),
            (WEATHER_MEASUREMENT_UUID, measurement_handler),
        ):
            try:
                await client.start_notify(uuid, handler)
            except Exception:
                LOGGER.debug(
                    "Weather BLE notification setup failed thing=%s uuid=%s",
                    self.thing_name,
                    uuid,
                    exc_info=True,
                )

    async def _execute_command(self, client: Any, command: ConnectivityCommand) -> None:
        target_redcon = normalize_target_redcon(command.power)
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    WEATHER_COMMAND_UUID,
                    encode_redcon_command(target_redcon),
                    response=True,
                ),
                timeout=self._config.command_timeout,
            )
        except Exception as err:
            await self._publish_command_result(
                command,
                status=COMMAND_FAILED,
                message=str(err),
            )
            return
        self._last_state = WeatherBleState(
            redcon=target_redcon,
            battery_mv=self._last_state.battery_mv,
            bme280_valid=self._last_state.bme280_valid,
        )
        await self._publish_state_report(self._last_state)
        await self._publish_command_result(command, status=COMMAND_SUCCEEDED, message=None)

    async def _handle_state_bytes(self, payload: bytes | bytearray | memoryview) -> None:
        try:
            state = parse_state_report(payload)
        except ValueError:
            LOGGER.warning("Ignoring invalid weather BLE state thing=%s", self.thing_name, exc_info=True)
            return
        await self._publish_state_report(state)

    async def _handle_measurement_bytes(self, payload: bytes | bytearray | memoryview) -> None:
        try:
            measurement = parse_measurement_report(payload)
        except ValueError:
            LOGGER.warning("Ignoring invalid weather BLE measurement thing=%s", self.thing_name, exc_info=True)
            return
        self._last_state = WeatherBleState(
            redcon=REDCON_ACTIVE,
            battery_mv=measurement.battery_mv or self._last_state.battery_mv,
            bme280_valid=True,
        )
        await self._publish_connectivity(
            presence=PRESENCE_ONLINE,
            control_availability=CONTROL_EVENTUAL,
            power=True,
            weather=WeatherMeasurements(
                measured_temperature=measurement.measured_temperature,
                measured_pressure=measurement.measured_pressure,
                measured_humidity=measurement.measured_humidity,
            ),
            battery_mv=measurement.battery_mv or self._last_state.battery_mv,
        )

    async def _publish_state_report(self, state: WeatherBleState) -> None:
        self._last_state = state
        await self._publish_connectivity(
            presence=PRESENCE_ONLINE,
            control_availability=CONTROL_EVENTUAL,
            power=state.redcon < REDCON_IDLE,
            weather=None,
            battery_mv=state.battery_mv,
        )

    async def _publish_connectivity(
        self,
        *,
        presence: str,
        control_availability: str,
        power: bool,
        weather: WeatherMeasurements | None,
        battery_mv: int | None,
    ) -> None:
        self._seq += 1
        native_identity: dict[str, Any] = {"bleLocalName": self.thing_name}
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
            weather=weather,
        )
        await self._bus.publish(build_state_topic(self.thing_name), state.to_json())
        LOGGER.info(
            "Published weather BLE state thing=%s presence=%s power=%s hasWeather=%s seq=%s",
            self.thing_name,
            presence,
            power,
            weather is not None,
            self._seq,
        )

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
            ).to_json(),
        )


class WeatherConnectivityBleService:
    def __init__(
        self,
        config: WeatherBleConfig,
        *,
        bus: LocalPubSub,
        session_factory: Callable[..., WeatherBleDeviceSession] = WeatherBleDeviceSession,
    ) -> None:
        self._config = config
        self._bus = bus
        self._session_factory = session_factory
        self._sessions: dict[str, WeatherBleDeviceSession] = {}
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
            subscriptions.append(
                await self._bus.subscribe(INVENTORY_TOPIC, self._handle_inventory)
            )
            subscriptions.append(
                await self._bus.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", self._handle_command)
            )
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
        if inventory.adapter_id != WEATHER_INVENTORY_ADAPTER_ID:
            LOGGER.debug(
                "Ignoring non-weather connectivity inventory adapterId=%s seq=%s devices=%s",
                inventory.adapter_id,
                inventory.seq,
                len(inventory.devices),
            )
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
                LOGGER.debug(
                    "Ignoring weather BLE command for unmanaged thing=%s",
                    command.thing_name,
                )
                return
            session = self._sessions.get(thing_name)
            if session is None:
                raise RuntimeError(f"weather BLE thing {thing_name!r} is not in inventory")
            await self._publish_command_result(
                command,
                status=COMMAND_ACCEPTED,
                message=None,
            )
            await session.enqueue_command(command)
        except Exception as err:
            LOGGER.warning("Invalid weather BLE command topic=%s error=%s", topic, err)
            try:
                command = ConnectivityCommand.from_payload(payload)
            except Exception:
                return
            await self._publish_command_result(
                command,
                status=COMMAND_FAILED,
                message=str(err),
            )

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
        raise RuntimeError("bleak is required for weather BLE connectivity")
    return BleakClient(
        _device_address(device) or device,
        services=(WEATHER_SERVICE_UUID,),
        timeout=timeout,
    )


async def _client_connect(client: Any, *, timeout: float) -> None:
    connect = getattr(client, "connect", None)
    if callable(connect):
        try:
            result = connect(dangerous_use_bleak_cache=True)
        except TypeError as err:
            if "dangerous_use_bleak_cache" not in str(err):
                raise
            result = connect()
        await asyncio.wait_for(result, timeout=timeout)
        return
    enter = getattr(client, "__aenter__", None)
    if callable(enter):
        await asyncio.wait_for(enter(), timeout=timeout)


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
        LOGGER.debug("Weather BLE cleanup after failed connect failed", exc_info=True)


def _is_transient_ble_error(err: Exception) -> bool:
    return isinstance(err, (TimeoutError, BleakError))


def _device_address(device: Any) -> str | None:
    address = getattr(device, "address", None)
    return address if isinstance(address, str) and address.strip() else None


def _advertisement_matches_weather_device(
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
        prog="weather-rig-connectivity-ble",
        description="txing weather BLE connected-idle adapter",
    )
    parser.add_argument("--adapter-id", default=os.getenv("WEATHER_BLE_ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--scan-timeout", type=float, default=float(os.getenv("WEATHER_BLE_SCAN_TIMEOUT", DEFAULT_SCAN_TIMEOUT)))
    parser.add_argument("--reconnect-delay", type=float, default=float(os.getenv("WEATHER_BLE_RECONNECT_DELAY", DEFAULT_RECONNECT_DELAY)))
    parser.add_argument("--connect-timeout", type=float, default=float(os.getenv("WEATHER_BLE_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT)))
    parser.add_argument("--command-timeout", type=float, default=float(os.getenv("WEATHER_BLE_COMMAND_TIMEOUT", DEFAULT_COMMAND_TIMEOUT)))
    parser.add_argument("--state-report-interval", type=float, default=float(os.getenv("WEATHER_BLE_STATE_REPORT_INTERVAL", DEFAULT_STATE_REPORT_INTERVAL)))
    parser.add_argument("--no-ble", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = WeatherBleConfig(
        adapter_id=args.adapter_id,
        scan_timeout=args.scan_timeout,
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
        service = WeatherConnectivityBleService(config, bus=bus)
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
