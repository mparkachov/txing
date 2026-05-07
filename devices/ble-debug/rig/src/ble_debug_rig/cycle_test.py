from __future__ import annotations

import argparse
import asyncio
import inspect
import platform
import shlex
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from bleak import BleakClient, BleakScanner
except ImportError as exc:  # pragma: no cover - exercised by manual environment setup.
    raise SystemExit(
        "Missing dependency 'bleak'. Run through uv: just ble-debug::rig::test 1"
    ) from exc


WEATHER_SERVICE_UUID = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_COMMAND_UUID = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_STATE_UUID = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100"

PROTOCOL_VERSION = 1
REDCON_ACTIVE = 3
REDCON_IDLE = 4
STATE_ACTIVE_FLAG = 0x01

COMMAND_STRUCT = struct.Struct("<BB")
STATE_STRUCT = struct.Struct("<BBBH")


class CycleError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class WeatherState:
    monotonic: float
    redcon: int
    active: bool
    battery_mv: int | None


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_field(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value)
    if text == "" or any(ch.isspace() for ch in text) or "'" in text or '"' in text:
        return shlex.quote(text)
    return text


def emit(event: str, **fields: object) -> None:
    suffix = "".join(f" {key}={format_field(value)}" for key, value in fields.items())
    print(f"{iso_now()} {event}{suffix}", flush=True)


async def await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def parse_state(payload: bytes | bytearray | memoryview) -> WeatherState:
    data = bytes(payload)
    if len(data) < STATE_STRUCT.size:
        raise CycleError("state", f"state payload too short: {len(data)}")
    version, redcon, flags, battery_mv = STATE_STRUCT.unpack_from(data)
    if version != PROTOCOL_VERSION:
        raise CycleError("state", f"unsupported state protocol version: {version}")
    return WeatherState(
        monotonic=time.monotonic(),
        redcon=redcon,
        active=bool(flags & STATE_ACTIVE_FLAG),
        battery_mv=battery_mv or None,
    )


def encode_command(redcon: int) -> bytes:
    return COMMAND_STRUCT.pack(PROTOCOL_VERSION, redcon)


def get_backend_name() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "bluez"
    if system == "darwin":
        return "corebluetooth"
    return system or "unknown"


def get_characteristic(services: Any, uuid: str) -> Any:
    getter = getattr(services, "get_characteristic", None)
    if getter is not None:
        return getter(uuid)
    for service in services:
        for characteristic in getattr(service, "characteristics", []):
            if str(characteristic.uuid).lower() == uuid:
                return characteristic
    return None


class BleCycleSession:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.started_monotonic = time.monotonic()
        self.client: BleakClient | None = None
        self.closing = False
        self.expecting_device_disconnect = False
        self.disconnected = asyncio.Event()
        self.unexpected_disconnect = False
        self.state_queue: asyncio.Queue[WeatherState] = asyncio.Queue()
        self.last_state: WeatherState | None = None
        self.command_char: Any = None
        self.state_char: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.args.connect_attempts + 1):
            try:
                device = await self.discover()
                started = time.monotonic()
                self.closing = False
                self.expecting_device_disconnect = False
                self.disconnected.clear()
                self.unexpected_disconnect = False
                client = BleakClient(
                    device,
                    disconnected_callback=self._on_disconnect,
                    timeout=self.args.connect_timeout,
                )
                await await_maybe(client.connect())
                self.client = client
                emit(
                    "connected",
                    name=self.args.name,
                    address=getattr(device, "address", "unknown"),
                    os=platform.system().lower(),
                    backend=get_backend_name(),
                    attempt=attempt,
                    connectMs=int((time.monotonic() - started) * 1000),
                    sinceStartMs=self.since_start_ms(),
                )
                await self._discover_services()
                await self._start_notify()
                await self.read_state()
                return
            except Exception as exc:  # noqa: BLE001 - surfaced directly to manual test output.
                last_error = exc
                await self._disconnect_after_failed_attempt()
                if attempt < self.args.connect_attempts:
                    emit(
                        "connect-retry",
                        attempt=attempt,
                        attempts=self.args.connect_attempts,
                        message=str(exc) or exc.__class__.__name__,
                    )
                    await asyncio.sleep(self.args.retry_delay)
        if isinstance(last_error, CycleError):
            raise last_error
        message = str(last_error) or (last_error.__class__.__name__ if last_error else "unknown")
        raise CycleError("connect", message)

    async def discover(self) -> Any:
        service_uuid = WEATHER_SERVICE_UUID.lower()
        seen = 0

        def matches(device: Any, advertisement_data: Any) -> bool:
            nonlocal seen
            local_name = advertisement_data.local_name or getattr(device, "name", None) or ""
            service_uuids = {uuid.lower() for uuid in (advertisement_data.service_uuids or [])}
            name_matches = local_name == self.args.name or getattr(device, "name", None) == self.args.name
            service_matches = (not self.args.require_service) or service_uuid in service_uuids
            if name_matches:
                seen += 1
                emit(
                    "adv",
                    name=local_name or self.args.name,
                    address=getattr(device, "address", "unknown"),
                    rssi=getattr(advertisement_data, "rssi", "unknown"),
                    service=int(service_uuid in service_uuids),
                )
            return name_matches and service_matches

        device = await BleakScanner.find_device_by_filter(matches, timeout=self.args.scan_timeout)
        if device is None:
            service_text = " with weather service UUID" if self.args.require_service else ""
            raise CycleError("discover", f"no matching advertisement for {self.args.name!r}{service_text}")
        return device

    async def _discover_services(self) -> None:
        client = self._client()
        started = time.monotonic()
        services = getattr(client, "services", None)
        if services is None:
            services = await await_maybe(client.get_services())
        self.command_char = get_characteristic(services, WEATHER_COMMAND_UUID)
        self.state_char = get_characteristic(services, WEATHER_STATE_UUID)
        emit(
            "services",
            command=int(self.command_char is not None),
            state=int(self.state_char is not None),
            servicesMs=int((time.monotonic() - started) * 1000),
        )
        if self.command_char is None or self.state_char is None:
            raise CycleError("services", "required command/state characteristics are missing")

    async def _start_notify(self) -> None:
        self.loop = asyncio.get_running_loop()

        def handler(_sender: object, payload: bytes | bytearray) -> None:
            try:
                state = parse_state(payload)
            except CycleError as exc:
                self.loop.call_soon_threadsafe(emit, "error", stage=exc.stage, message=str(exc))
                return
            self.loop.call_soon_threadsafe(self._record_state, state)

        await await_maybe(self._client().start_notify(self.state_char, handler))
        emit("notify", characteristic="state", enabled=1)

    async def read_state(self) -> WeatherState:
        state = parse_state(await await_maybe(self._client().read_gatt_char(self.state_char)))
        self._record_state(state)
        return state

    async def write_redcon(self, redcon: int) -> float:
        payload = encode_command(redcon)
        started = time.monotonic()
        await await_maybe(self._client().write_gatt_char(self.command_char, payload, response=True))
        emit("command", redcon=redcon, payload=payload.hex())
        return started

    async def run_cycles(self) -> None:
        cycle_battery_counts: list[int] = []
        all_battery_mv: list[int] = []
        started = time.monotonic()

        for cycle in range(1, self.args.repetitions + 1):
            cycle_started = time.monotonic()
            emit("cycle-start", cycle=cycle, cycles=self.args.repetitions, sinceStartMs=self.since_start_ms())
            if not self._is_connected():
                await self.connect()

            self._drain_state_queue()
            wake_command_at = await self.write_redcon(REDCON_ACTIVE)
            wake_state = await self.wait_for_redcon(
                REDCON_ACTIVE,
                stage=f"cycle {cycle}: wake",
                deadline_seconds=self.args.wake_deadline,
                after_monotonic=wake_command_at,
            )
            wake_latency_ms = int((wake_state.monotonic - wake_command_at) * 1000)
            emit(
                "wake-ok",
                cycle=cycle,
                latencyMs=wake_latency_ms,
                cycleElapsedMs=int((wake_state.monotonic - cycle_started) * 1000),
                sinceStartMs=int((wake_state.monotonic - self.started_monotonic) * 1000),
                batteryMv=wake_state.battery_mv or 0,
            )

            battery_states = await self.collect_active_battery_states(
                cycle=cycle,
                first_state=wake_state,
                active_until=wake_command_at + self.args.wake_seconds,
            )
            battery_values = [state.battery_mv for state in battery_states if state.battery_mv is not None]
            if len(battery_values) < self.args.min_battery:
                raise CycleError(
                    "battery",
                    (
                        f"cycle {cycle}: got {len(battery_values)} active battery updates, "
                        f"need {self.args.min_battery}"
                    ),
                )
            cycle_battery_counts.append(len(battery_values))
            all_battery_mv.extend(battery_values)

            self.expecting_device_disconnect = not self.args.keep_connected_during_sleep
            sleep_command_at = await self.write_redcon(REDCON_IDLE)
            sleep_state = await self.wait_for_redcon(
                REDCON_IDLE,
                stage=f"cycle {cycle}: sleep",
                deadline_seconds=self.args.sleep_deadline,
                after_monotonic=sleep_command_at,
            )
            emit(
                "sleep-ok",
                cycle=cycle,
                latencyMs=int((sleep_state.monotonic - sleep_command_at) * 1000),
                batteryMv=sleep_state.battery_mv or 0,
            )

            cycle_deadline = cycle_started + self.args.cycle_seconds
            if self.args.keep_connected_during_sleep:
                await self.monitor_sleep_window(cycle=cycle, until=cycle_deadline)
            else:
                await self.wait_for_device_disconnect(
                    cycle=cycle,
                    after_monotonic=sleep_state.monotonic,
                    deadline_seconds=self.args.disconnect_deadline,
                )
                await self.sleep_disconnected_window(cycle=cycle, until=cycle_deadline)

            emit(
                "summary",
                command="cycle",
                cycle=cycle,
                cycles=self.args.repetitions,
                batteryCount=len(battery_values),
                batteryMinMv=min(battery_values),
                batteryMaxMv=max(battery_values),
                sleepLink="connected" if self.args.keep_connected_during_sleep else "disconnected",
            )

        emit(
            "summary",
            command="test",
            cycles=self.args.repetitions,
            elapsedSec=int(time.monotonic() - started),
            batteryCount=sum(cycle_battery_counts),
            batteryMinMv=min(all_battery_mv) if all_battery_mv else 0,
            batteryMaxMv=max(all_battery_mv) if all_battery_mv else 0,
            sleepLink="connected" if self.args.keep_connected_during_sleep else "disconnected",
        )

    async def collect_active_battery_states(
        self,
        *,
        cycle: int,
        first_state: WeatherState,
        active_until: float,
    ) -> list[WeatherState]:
        states: list[WeatherState] = []
        if self._is_active_battery_state(first_state):
            states.append(first_state)

        while time.monotonic() < active_until:
            try:
                state = await self.next_state(timeout=min(1.0, max(0.0, active_until - time.monotonic())))
            except TimeoutError:
                continue
            if state.redcon == REDCON_IDLE and state.monotonic < active_until:
                raise CycleError("wake", f"cycle {cycle}: device returned to sleep during wake window")
            if self._is_active_battery_state(state):
                states.append(state)
                emit("battery", cycle=cycle, count=len(states), batteryMv=state.battery_mv or 0)
        return states

    async def monitor_sleep_window(self, *, cycle: int, until: float) -> None:
        while time.monotonic() < until:
            try:
                state = await self.next_state(timeout=min(1.0, max(0.0, until - time.monotonic())))
            except TimeoutError:
                continue
            if state.redcon == REDCON_ACTIVE or state.active:
                raise CycleError("sleep", f"cycle {cycle}: active state observed during sleep window")

    async def sleep_disconnected_window(self, *, cycle: int, until: float) -> None:
        remaining = until - time.monotonic()
        if remaining <= 0:
            return
        emit("sleep-idle", cycle=cycle, mode="advertising", durationMs=int(remaining * 1000))
        await asyncio.sleep(remaining)

    async def wait_for_redcon(
        self,
        redcon: int,
        *,
        stage: str,
        deadline_seconds: float,
        after_monotonic: float,
    ) -> WeatherState:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            try:
                state = await self.next_state(timeout=min(1.0, max(0.0, deadline - time.monotonic())))
            except CycleError as exc:
                if exc.stage == "disconnect":
                    raise CycleError(stage, f"disconnected before state {redcon}") from exc
                raise
            except TimeoutError:
                continue
            if state.monotonic >= after_monotonic and state.redcon == redcon:
                return state
        raise CycleError(stage, f"state {redcon} deadline expired")

    async def wait_for_device_disconnect(
        self,
        *,
        cycle: int,
        after_monotonic: float,
        deadline_seconds: float,
    ) -> None:
        started = time.monotonic()
        if not self.disconnected.is_set():
            try:
                await asyncio.wait_for(self.disconnected.wait(), timeout=deadline_seconds)
            except TimeoutError as exc:
                raise CycleError(
                    "sleep",
                    f"cycle {cycle}: device did not disconnect after REDCON 4",
                ) from exc

        self.client = None
        emit(
            "sleep-disconnect",
            cycle=cycle,
            source="device",
            latencyMs=max(0, int((time.monotonic() - after_monotonic) * 1000)),
            waitMs=max(0, int((time.monotonic() - started) * 1000)),
        )

    async def next_state(self, *, timeout: float) -> WeatherState:
        state_task = asyncio.create_task(self.state_queue.get())
        disconnect_task = asyncio.create_task(self.disconnected.wait())
        try:
            done, pending = await asyncio.wait(
                {state_task, disconnect_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise TimeoutError
            if state_task in done:
                return state_task.result()
            if disconnect_task in done:
                raise CycleError("disconnect", "unexpected disconnect")
            raise TimeoutError
        finally:
            for task in (state_task, disconnect_task):
                if not task.done():
                    task.cancel()

    async def close(self) -> None:
        client = self.client
        self.closing = True
        self.expecting_device_disconnect = False
        if client is not None:
            try:
                if getattr(client, "is_connected", False):
                    try:
                        await await_maybe(client.stop_notify(self.state_char))
                    except Exception:
                        pass
                    await await_maybe(client.disconnect())
            finally:
                self.client = None

    def _on_disconnect(self, client: BleakClient) -> None:
        del client
        unexpected = not (self.closing or self.expecting_device_disconnect)
        self.unexpected_disconnect = unexpected
        self.client = None
        emit("disconnect", name=self.args.name, unexpected=int(unexpected))
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.disconnected.set)

    async def _disconnect_after_failed_attempt(self) -> None:
        client = self.client
        self.client = None
        self.expecting_device_disconnect = False
        if client is not None:
            try:
                if getattr(client, "is_connected", False):
                    await await_maybe(client.disconnect())
            except Exception:
                pass

    def _record_state(self, state: WeatherState) -> None:
        self.last_state = state
        self.state_queue.put_nowait(state)
        emit(
            "state",
            redcon=state.redcon,
            active=int(state.active),
            batteryMv=state.battery_mv or 0,
        )

    def _drain_state_queue(self) -> None:
        while True:
            try:
                self.state_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _client(self) -> BleakClient:
        if self.client is None:
            raise CycleError("connect", "not connected")
        return self.client

    def since_start_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)

    def _is_connected(self) -> bool:
        client = self.client
        return bool(client is not None and getattr(client, "is_connected", False))

    @staticmethod
    def _is_active_battery_state(state: WeatherState) -> bool:
        return state.redcon == REDCON_ACTIVE and state.active and state.battery_mv is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run BLE wake/sleep cycles. Each cycle wakes REDCON 3 for "
            "30 seconds, requires battery state updates, then sleeps REDCON 4 for "
            "the rest of the minute. By default the test waits for the device to "
            "disconnect itself after sleep-ok, so sleep current is measured in "
            "advertising idle mode."
        )
    )
    parser.add_argument("repetitions", type=int, help="number of one-minute cycles to run")
    parser.add_argument("--name", default="weather-q8zbgb", help="BLE local name to discover")
    parser.add_argument("--wake-seconds", type=float, default=30.0)
    parser.add_argument("--cycle-seconds", type=float, default=60.0)
    parser.add_argument("--min-battery", type=int, default=3)
    parser.add_argument("--wake-deadline", type=float, default=10.0)
    parser.add_argument("--sleep-deadline", type=float, default=10.0)
    parser.add_argument("--scan-timeout", type=float, default=60.0)
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    parser.add_argument("--connect-attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument(
        "--disconnect-deadline",
        type=float,
        default=5.0,
        help="seconds to wait for device-initiated disconnect after REDCON 4",
    )
    parser.add_argument(
        "--keep-connected-during-sleep",
        action="store_true",
        help=(
            "keep the BLE connection open after REDCON 4. This measures connected "
            "sleep current, which is expected to be much higher than advertising idle."
        ),
    )
    parser.add_argument(
        "--no-require-service",
        dest="require_service",
        action="store_false",
        help="match by name only instead of requiring the weather service UUID in advertising",
    )
    parser.set_defaults(require_service=True)
    return parser


async def run(args: argparse.Namespace) -> int:
    if args.repetitions <= 0:
        raise CycleError("args", "repetitions must be greater than zero")
    if args.wake_seconds <= 0 or args.cycle_seconds <= 0:
        raise CycleError("args", "wake-seconds and cycle-seconds must be greater than zero")
    if args.wake_seconds >= args.cycle_seconds:
        raise CycleError("args", "wake-seconds must be less than cycle-seconds")
    if args.min_battery <= 0:
        raise CycleError("args", "min-battery must be greater than zero")

    emit(
        "starting",
        command="test",
        cycles=args.repetitions,
        name=args.name,
        wakeSeconds=args.wake_seconds,
        cycleSeconds=args.cycle_seconds,
        minBattery=args.min_battery,
    )
    session = BleCycleSession(args)
    try:
        await session.run_cycles()
    finally:
        await session.close()
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        emit("error", stage="signal", message="interrupted")
        raise SystemExit(130) from None
    except CycleError as exc:
        emit("error", stage=exc.stage, message=str(exc))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
