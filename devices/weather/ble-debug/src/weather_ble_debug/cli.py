from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import sys
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .ble_stack import BleStackConfig, detect_ble_stack
from .protocol import (
    REDCON_ACTIVE,
    REDCON_IDLE,
    WEATHER_COMMAND_UUID,
    WEATHER_MEASUREMENT_UUID,
    WEATHER_SERVICE_UUID,
    WEATHER_STATE_UUID,
    WeatherMeasurement,
    WeatherState,
    encode_command,
    parse_measurement,
    parse_state,
)

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - startup validation covers real use
    BleakClient = None
    BleakScanner = None


EventWriter = Callable[[str], None]


class DebugError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(slots=True)
class TargetAdvertisement:
    device: Any
    name: str
    address: str
    rssi: int | None
    services: tuple[str, ...]


class EventSink:
    def __init__(self, writer: EventWriter | None = None) -> None:
        self._writer = writer or print

    def emit(self, event: str, **fields: object) -> None:
        self._writer(format_event(event, **fields))


class MeasurementCadence:
    def __init__(self) -> None:
        self._timestamps: list[float] = []

    @property
    def count(self) -> int:
        return len(self._timestamps)

    def record(self, timestamp: float | None = None) -> None:
        self._timestamps.append(time.monotonic() if timestamp is None else timestamp)

    def summary_fields(self) -> dict[str, object]:
        if len(self._timestamps) < 2:
            return {"measurementCount": len(self._timestamps)}
        intervals_ms = [
            int(round((right - left) * 1000))
            for left, right in zip(self._timestamps, self._timestamps[1:])
        ]
        return {
            "measurementCount": len(self._timestamps),
            "minIntervalMs": min(intervals_ms),
            "maxIntervalMs": max(intervals_ms),
            "avgIntervalMs": int(round(sum(intervals_ms) / len(intervals_ms))),
        }

    def stable(self, *, expected_seconds: float = 1.0, tolerance_seconds: float = 0.35) -> bool:
        if len(self._timestamps) < 2:
            return False
        low = expected_seconds - tolerance_seconds
        high = expected_seconds + tolerance_seconds
        return all(
            low <= right - left <= high
            for left, right in zip(self._timestamps, self._timestamps[1:])
        )


def format_event(event: str, **fields: object) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    parts = [timestamp, event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value)
    if not text:
        return "-"
    if any(ch.isspace() for ch in text):
        return repr(text)
    return text


class WeatherBleDebugClient:
    def __init__(
        self,
        *,
        name: str,
        timeout: float = 30.0,
        sink: EventSink | None = None,
        scanner_factory: Callable[..., Any] | None = None,
        client_factory: Callable[..., Any] | None = None,
        stack: BleStackConfig | None = None,
        adapter: str | None = None,
    ) -> None:
        self.name = name
        self.timeout = timeout
        self.sink = sink or EventSink()
        self.stack = stack or detect_ble_stack(adapter=adapter)
        self.scanner_factory = scanner_factory or _default_scanner
        self.client_factory = client_factory or _default_client
        self.client: Any | None = None
        self.last_state: WeatherState | None = None
        self.last_measurement: WeatherMeasurement | None = None
        self.state_queue: asyncio.Queue[WeatherState] = asyncio.Queue()
        self.measurement_queue: asyncio.Queue[WeatherMeasurement] = asyncio.Queue()
        self.cadence = MeasurementCadence()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._disconnect_event: asyncio.Event | None = None
        self._intentional_disconnect = False
        self._disconnect_reported = False

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._disconnect_event = asyncio.Event()
        self._intentional_disconnect = False
        self._disconnect_reported = False
        advertisement = await discover_target(
            name=self.name,
            timeout=self.timeout,
            sink=self.sink,
            scanner_factory=self.scanner_factory,
            stack=self.stack,
        )
        client = self._create_client(advertisement.device)
        self.client = client
        try:
            connect_started = time.monotonic()
            await _await_maybe(client.connect())
            connect_ms = int(round((time.monotonic() - connect_started) * 1000))
            self.sink.emit(
                "connected",
                name=self.name,
                address=advertisement.address,
                **self.stack.event_fields(),
                connectMs=connect_ms,
            )
            services_started = time.monotonic()
            services = await ensure_services(client)
            services_ms = int(round((time.monotonic() - services_started) * 1000))
            self._emit_services(services, services_ms=services_ms)
            await self._read_initial_state()
            await self._start_notifications()
        except Exception as err:
            await self.disconnect(emit=False)
            if isinstance(err, DebugError):
                raise
            raise DebugError("connect", str(err) or type(err).__name__) from err

    async def disconnect(self, *, emit: bool = True) -> None:
        if self.client is None:
            return
        client = self.client
        self.client = None
        self._intentional_disconnect = True
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            await _await_maybe(disconnect())
        if emit:
            self.sink.emit("disconnect", name=self.name, unexpected=0)

    async def write_redcon(self, redcon: int) -> None:
        client = self._require_client()
        payload = encode_command(redcon)
        await _await_maybe(client.write_gatt_char(WEATHER_COMMAND_UUID, payload, response=True))
        self.sink.emit("command", redcon=redcon, payload=payload.hex())

    async def wake(self, *, deadline: float) -> None:
        start = time.monotonic()
        measurement_count = self.cadence.count
        _drain_queue(self.state_queue)
        await self.write_redcon(REDCON_ACTIVE)
        await self.wait_for_state(REDCON_ACTIVE, deadline=deadline, accept_current=False)
        remaining = max(deadline - (time.monotonic() - start), 0.001)
        await self.wait_for_measurement_after(measurement_count, deadline=remaining)
        self.sink.emit("wake-ok", latencyMs=int(round((time.monotonic() - start) * 1000)))

    async def sleep(self, *, deadline: float) -> None:
        start = time.monotonic()
        _drain_queue(self.state_queue)
        await self.write_redcon(REDCON_IDLE)
        await self.wait_for_state(REDCON_IDLE, deadline=deadline, accept_current=False)
        self.sink.emit("sleep-ok", latencyMs=int(round((time.monotonic() - start) * 1000)))

    async def wait_for_state(
        self,
        redcon: int,
        *,
        deadline: float,
        accept_current: bool = True,
    ) -> WeatherState:
        if accept_current and self.last_state is not None and self.last_state.redcon == redcon:
            return self.last_state
        stage = "wake" if redcon == REDCON_ACTIVE else "sleep"
        message = f"state {redcon} deadline expired"
        end = time.monotonic() + deadline
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise DebugError(stage, message)
            state = await self._queue_get_or_disconnect(
                self.state_queue,
                timeout=remaining,
                stage=stage,
                timeout_message=message,
            )
            if state.redcon == redcon:
                return state

    async def wait_for_measurement_after(
        self,
        count: int,
        *,
        deadline: float,
    ) -> WeatherMeasurement:
        if self.cadence.count > count and self.last_measurement is not None:
            return self.last_measurement
        end = time.monotonic() + deadline
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise DebugError("wake", "measurement deadline expired")
            measurement = await self._queue_get_or_disconnect(
                self.measurement_queue,
                timeout=remaining,
                stage="wake",
                timeout_message="measurement deadline expired",
            )
            if self.cadence.count > count:
                return measurement

    async def observe(self, seconds: float, *, stage: str = "observe") -> None:
        if seconds <= 0:
            self._raise_if_disconnected(stage)
            return
        disconnect_event = self._disconnect_event
        if disconnect_event is None:
            await asyncio.sleep(seconds)
            return
        sleep_task = asyncio.create_task(asyncio.sleep(seconds))
        disconnect_task = asyncio.create_task(disconnect_event.wait())
        done, pending = await asyncio.wait(
            {sleep_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if disconnect_task in done and disconnect_event.is_set():
            raise DebugError(stage, "unexpected disconnect")

    def emit_summary(self, *, command: str, **fields: object) -> None:
        self.sink.emit(
            "summary",
            command=command,
            state=self.last_state.redcon if self.last_state else None,
            **self.stack.event_fields(),
            **self.cadence.summary_fields(),
            **fields,
        )

    def _require_client(self) -> Any:
        if self.client is None:
            raise DebugError("connect", "not connected")
        return self.client

    async def _read_initial_state(self) -> None:
        client = self._require_client()
        state = parse_state(await _await_maybe(client.read_gatt_char(WEATHER_STATE_UUID)))
        self._record_state(state)
        if not state.bme280_valid:
            return
        try:
            measurement = parse_measurement(
                await _await_maybe(client.read_gatt_char(WEATHER_MEASUREMENT_UUID))
            )
        except Exception:
            return
        self._record_measurement(measurement)

    async def _start_notifications(self) -> None:
        client = self._require_client()
        loop = asyncio.get_running_loop()

        def state_handler(_sender: object, payload: bytes | bytearray) -> None:
            state = parse_state(payload)
            loop.call_soon_threadsafe(self._record_state, state)

        def measurement_handler(_sender: object, payload: bytes | bytearray) -> None:
            measurement = parse_measurement(payload)
            loop.call_soon_threadsafe(self._record_measurement, measurement)

        await _await_maybe(client.start_notify(WEATHER_STATE_UUID, state_handler))
        self.sink.emit("notify", characteristic="state", enabled=True)
        await _await_maybe(client.start_notify(WEATHER_MEASUREMENT_UUID, measurement_handler))
        self.sink.emit("notify", characteristic="measurement", enabled=True)

    def _record_state(self, state: WeatherState) -> None:
        self.last_state = state
        self.state_queue.put_nowait(state)
        self.sink.emit(
            "state",
            redcon=state.redcon,
            active=int(state.active),
            bme280=int(state.bme280_valid),
            batteryMv=state.battery_mv,
        )

    def _record_measurement(self, measurement: WeatherMeasurement) -> None:
        self.last_measurement = measurement
        self.cadence.record()
        self.measurement_queue.put_nowait(measurement)
        self.sink.emit(
            "measurement",
            temperatureC=measurement.temperature_c,
            pressureKpa=measurement.pressure_kpa,
            humidityPercent=measurement.humidity_percent,
            batteryMv=measurement.battery_mv,
        )

    def _create_client(self, device: Any) -> Any:
        return self.client_factory(
            device,
            disconnected_callback=self._handle_client_disconnect,
            timeout=self.timeout,
            services=[WEATHER_SERVICE_UUID],
            client_kwargs=self.stack.client_kwargs,
        )

    def _handle_client_disconnect(self, _client: Any) -> None:
        if self._intentional_disconnect or self._disconnect_reported:
            return
        loop = self._loop
        if loop is None:
            self._record_unexpected_disconnect()
        else:
            loop.call_soon_threadsafe(self._record_unexpected_disconnect)

    def _record_unexpected_disconnect(self) -> None:
        if self._intentional_disconnect or self._disconnect_reported:
            return
        self._disconnect_reported = True
        if self._disconnect_event is not None:
            self._disconnect_event.set()
        self.sink.emit("disconnect", name=self.name, unexpected=1)

    async def _queue_get_or_disconnect(
        self,
        queue: asyncio.Queue[Any],
        *,
        timeout: float,
        stage: str,
        timeout_message: str,
    ) -> Any:
        self._raise_if_disconnected(stage)
        disconnect_event = self._disconnect_event
        if disconnect_event is None:
            try:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError as err:
                raise DebugError(stage, timeout_message) from err

        queue_task = asyncio.create_task(queue.get())
        disconnect_task = asyncio.create_task(disconnect_event.wait())
        done, pending = await asyncio.wait(
            {queue_task, disconnect_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if not done:
            raise DebugError(stage, timeout_message)
        if disconnect_task in done and disconnect_event.is_set():
            raise DebugError(stage, "unexpected disconnect")
        return queue_task.result()

    def _raise_if_disconnected(self, stage: str) -> None:
        if self._disconnect_event is not None and self._disconnect_event.is_set():
            raise DebugError(stage, "unexpected disconnect")

    def _emit_services(self, services: Any, *, services_ms: int) -> None:
        self.sink.emit(
            "services",
            command=int(_has_characteristic(services, WEATHER_COMMAND_UUID)),
            state=int(_has_characteristic(services, WEATHER_STATE_UUID)),
            measurement=int(_has_characteristic(services, WEATHER_MEASUREMENT_UUID)),
            servicesMs=services_ms,
        )


async def discover_target(
    *,
    name: str,
    timeout: float,
    sink: EventSink,
    scanner_factory: Callable[..., Any] | None = None,
    stack: BleStackConfig | None = None,
) -> TargetAdvertisement:
    stack = stack or detect_ble_stack()
    loop = asyncio.get_running_loop()
    found: asyncio.Future[TargetAdvertisement] = loop.create_future()

    def detection_callback(device: Any, advertisement_data: Any) -> None:
        adv_name = _advertisement_name(device, advertisement_data)
        services = _advertisement_services(advertisement_data)
        service_match = WEATHER_SERVICE_UUID in services
        if adv_name == name:
            target = TargetAdvertisement(
                device=device,
                name=adv_name,
                address=_device_address(device),
                rssi=_advertisement_rssi(advertisement_data),
                services=tuple(sorted(services)),
            )
            sink.emit(
                "adv",
                name=target.name,
                address=target.address,
                rssi=target.rssi,
                service=int(service_match),
            )
            if service_match and not found.done():
                found.set_result(target)

    scanner = (scanner_factory or _default_scanner)(
        detection_callback=detection_callback,
        service_uuids=[WEATHER_SERVICE_UUID],
        **stack.scanner_kwargs,
    )
    await _start_scanner(scanner)
    try:
        return await asyncio.wait_for(found, timeout=timeout)
    except TimeoutError as err:
        raise DebugError("discover", f"no matching advertisement for {name!r}") from err
    finally:
        await _stop_scanner(scanner)


async def scan(
    *,
    name: str,
    timeout: float,
    sink: EventSink,
    scanner_factory: Callable[..., Any] | None = None,
    stack: BleStackConfig | None = None,
) -> None:
    stack = stack or detect_ble_stack()
    count = 0

    def detection_callback(device: Any, advertisement_data: Any) -> None:
        nonlocal count
        adv_name = _advertisement_name(device, advertisement_data)
        services = _advertisement_services(advertisement_data)
        service_match = WEATHER_SERVICE_UUID in services
        if adv_name != name:
            return
        count += 1
        sink.emit(
            "adv",
            name=adv_name,
            address=_device_address(device),
            rssi=_advertisement_rssi(advertisement_data),
            service=int(service_match),
        )

    scanner = (scanner_factory or _default_scanner)(
        detection_callback=detection_callback,
        service_uuids=[WEATHER_SERVICE_UUID],
        **stack.scanner_kwargs,
    )
    await _start_scanner(scanner)
    try:
        await asyncio.sleep(timeout)
    finally:
        await _stop_scanner(scanner)
    sink.emit("summary", command="scan", advCount=count, **stack.event_fields())


async def ensure_services(client: Any) -> Any:
    services = None
    try:
        services = getattr(client, "services")
    except Exception as err:
        if "service discovery has not been performed yet" not in str(err).lower():
            raise
    if services is None:
        get_services = getattr(client, "get_services", None)
        if not callable(get_services):
            raise DebugError("services", "client has no get_services method")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            services = await _await_maybe(get_services())
    for uuid in (WEATHER_COMMAND_UUID, WEATHER_STATE_UUID, WEATHER_MEASUREMENT_UUID):
        if not _has_characteristic(services, uuid):
            raise DebugError("services", f"missing characteristic {uuid}")
    return services


async def run_inspect(args: argparse.Namespace, sink: EventSink) -> None:
    session = WeatherBleDebugClient(
        name=args.name,
        timeout=args.timeout,
        sink=sink,
        adapter=args.adapter,
    )
    await session.connect()
    try:
        session.emit_summary(command="inspect")
    finally:
        await session.disconnect()


async def run_idle(args: argparse.Namespace, sink: EventSink) -> None:
    session = WeatherBleDebugClient(
        name=args.name,
        timeout=args.timeout,
        sink=sink,
        adapter=args.adapter,
    )
    await session.connect()
    try:
        await session.observe(args.duration, stage="idle")
        session.emit_summary(command="idle", durationSec=args.duration)
    finally:
        await session.disconnect()


async def run_wake(args: argparse.Namespace, sink: EventSink) -> None:
    session = WeatherBleDebugClient(
        name=args.name,
        timeout=args.timeout,
        sink=sink,
        adapter=args.adapter,
    )
    await session.connect()
    try:
        await session.wake(deadline=args.deadline)
        await session.observe(args.active_seconds, stage="wake")
        session.emit_summary(command="wake", activeSeconds=args.active_seconds)
    finally:
        await session.disconnect()


async def run_sleep(args: argparse.Namespace, sink: EventSink) -> None:
    session = WeatherBleDebugClient(
        name=args.name,
        timeout=args.timeout,
        sink=sink,
        adapter=args.adapter,
    )
    await session.connect()
    try:
        await session.sleep(deadline=args.deadline)
        session.emit_summary(command="sleep")
    finally:
        await session.disconnect()


async def run_soak(args: argparse.Namespace, sink: EventSink) -> None:
    session = WeatherBleDebugClient(
        name=args.name,
        timeout=args.timeout,
        sink=sink,
        adapter=args.adapter,
    )
    await session.connect()
    try:
        for cycle in range(1, args.cycles + 1):
            try:
                await session.wake(deadline=args.deadline)
                await session.observe(args.active_seconds, stage="soak")
                await session.sleep(deadline=args.deadline)
                await session.observe(args.idle_seconds, stage="soak")
            except DebugError as err:
                raise DebugError("soak", f"cycle {cycle}: {err.stage}: {err}") from err
            sink.emit("summary", command="soak-cycle", cycle=cycle, cycles=args.cycles)
        session.emit_summary(command="soak", cycles=args.cycles)
    finally:
        await session.disconnect()


async def run_args(args: argparse.Namespace, sink: EventSink) -> None:
    if args.command == "scan":
        await scan(
            name=args.name,
            timeout=args.timeout,
            sink=sink,
            stack=detect_ble_stack(adapter=args.adapter),
        )
    elif args.command == "inspect":
        await run_inspect(args, sink)
    elif args.command == "idle":
        await run_idle(args, sink)
    elif args.command == "wake":
        await run_wake(args, sink)
    elif args.command == "sleep":
        await run_sleep(args, sink)
    elif args.command == "soak":
        await run_soak(args, sink)
    else:  # pragma: no cover - argparse prevents this
        raise DebugError("cli", f"unsupported command {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weather-ble-debug")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    _add_name_timeout(scan_parser)

    inspect_parser = subparsers.add_parser("inspect")
    _add_name_timeout(inspect_parser)

    idle_parser = subparsers.add_parser("idle")
    _add_name_timeout(idle_parser)
    idle_parser.add_argument("--duration", type=float, default=300.0)

    wake_parser = subparsers.add_parser("wake")
    _add_name_timeout(wake_parser)
    wake_parser.add_argument("--deadline", type=float, default=10.0)
    wake_parser.add_argument("--active-seconds", type=float, default=30.0)

    sleep_parser = subparsers.add_parser("sleep")
    _add_name_timeout(sleep_parser)
    sleep_parser.add_argument("--deadline", type=float, default=10.0)

    soak_parser = subparsers.add_parser("soak")
    _add_name_timeout(soak_parser)
    soak_parser.add_argument("--cycles", type=int, default=50)
    soak_parser.add_argument("--active-seconds", type=float, default=20.0)
    soak_parser.add_argument("--idle-seconds", type=float, default=20.0)
    soak_parser.add_argument("--deadline", type=float, default=10.0)
    return parser


def _add_name_timeout(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--adapter",
        default=os.environ.get("WEATHER_BLE_DEBUG_ADAPTER"),
        help="Linux/BlueZ adapter, for example hci0. Defaults to the BlueZ default adapter.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sink = EventSink()
    try:
        asyncio.run(run_args(args, sink))
    except KeyboardInterrupt:
        sink.emit("error", stage="signal", message="interrupted")
        return 130
    except DebugError as err:
        sink.emit("error", stage=err.stage, message=str(err))
        return 2
    except Exception as err:  # pragma: no cover - safety net for hardware debugging
        sink.emit("error", stage="unexpected", message=str(err) or type(err).__name__)
        return 1
    return 0


def _default_scanner(**kwargs: Any) -> Any:
    if BleakScanner is None:
        raise DebugError("startup", "bleak is required")
    return BleakScanner(**kwargs)


def _default_client(
    device: Any,
    *,
    disconnected_callback: Callable[[Any], None],
    timeout: float,
    services: list[str],
    client_kwargs: dict[str, Any],
) -> Any:
    if BleakClient is None:
        raise DebugError("startup", "bleak is required")
    kwargs = {
        "disconnected_callback": disconnected_callback,
        "timeout": timeout,
        "services": services,
        **client_kwargs,
    }
    try:
        return BleakClient(device, **kwargs)
    except TypeError:
        kwargs.pop("services", None)
        return BleakClient(device, **kwargs)


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _start_scanner(scanner: Any) -> None:
    start = getattr(scanner, "start", None)
    if not callable(start):
        raise DebugError("discover", "scanner has no start method")
    await _await_maybe(start())


async def _stop_scanner(scanner: Any) -> None:
    stop = getattr(scanner, "stop", None)
    if callable(stop):
        await _await_maybe(stop())


def _advertisement_name(device: Any, advertisement_data: Any) -> str | None:
    for value in (
        getattr(advertisement_data, "local_name", None),
        getattr(device, "name", None),
    ):
        if isinstance(value, str) and value:
            return value
    return None


def _advertisement_services(advertisement_data: Any) -> set[str]:
    return {
        str(uuid).lower()
        for uuid in (getattr(advertisement_data, "service_uuids", None) or ())
    }


def _advertisement_rssi(advertisement_data: Any) -> int | None:
    value = getattr(advertisement_data, "rssi", None)
    return value if isinstance(value, int) else None


def _device_address(device: Any) -> str:
    value = getattr(device, "address", None)
    return value if isinstance(value, str) and value else "-"


def _drain_queue(queue: asyncio.Queue[Any]) -> None:
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return


def _has_characteristic(services: Any, uuid: str) -> bool:
    get_characteristic = getattr(services, "get_characteristic", None)
    if callable(get_characteristic):
        return get_characteristic(uuid) is not None
    try:
        iterator = iter(services or ())
    except TypeError:
        return False
    for service in iterator:
        for characteristic in getattr(service, "characteristics", ()):
            if str(getattr(characteristic, "uuid", "")).lower() == uuid:
                return True
    return False


if __name__ == "__main__":
    sys.exit(main())
