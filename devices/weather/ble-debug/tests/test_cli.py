from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from typing import Any

from weather_ble_debug.ble_stack import detect_ble_stack
from weather_ble_debug.cli import (
    DebugError,
    EventSink,
    MeasurementCadence,
    WeatherBleDebugClient,
    discover_target,
    format_event,
    scan,
)
from weather_ble_debug.protocol import (
    REDCON_ACTIVE,
    REDCON_IDLE,
    WEATHER_COMMAND_UUID,
    WEATHER_MEASUREMENT_UUID,
    WEATHER_SERVICE_UUID,
    WEATHER_STATE_UUID,
    encode_command,
    encode_measurement_for_test,
    encode_state_for_test,
)


@dataclass(slots=True)
class FakeDevice:
    address: str = "AA:BB:CC:DD:EE:FF"
    name: str = "weather-1"


@dataclass(slots=True)
class FakeAdvertisementData:
    local_name: str = "weather-1"
    rssi: int = -42
    service_uuids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.service_uuids is None:
            self.service_uuids = [WEATHER_SERVICE_UUID]


class FakeScanner:
    instances: list[FakeScanner] = []

    def __init__(self, *, detection_callback: Any, service_uuids: list[str], **kwargs: Any) -> None:
        self.detection_callback = detection_callback
        self.service_uuids = service_uuids
        self.kwargs = kwargs
        self.stopped = False
        self.instances.append(self)

    async def start(self) -> None:
        self.detection_callback(FakeDevice(), FakeAdvertisementData())

    async def stop(self) -> None:
        self.stopped = True


class FakeServices:
    def get_characteristic(self, uuid: str) -> object | None:
        if uuid in (WEATHER_COMMAND_UUID, WEATHER_STATE_UUID, WEATHER_MEASUREMENT_UUID):
            return object()
        return None


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(
        self,
        device: FakeDevice,
        *,
        disconnected_callback: Any | None = None,
        timeout: float | None = None,
        services: list[str] | None = None,
        client_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.device = device
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.services_filter = services
        self.client_kwargs = client_kwargs or {}
        self.connected = False
        self.services = FakeServices()
        self.notifications: dict[str, Any] = {}
        self.writes: list[tuple[str, bytes, bool]] = []
        self.current_redcon = REDCON_IDLE
        self.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    def trigger_unexpected_disconnect(self) -> None:
        self.connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    async def read_gatt_char(self, uuid: str) -> bytes:
        if uuid == WEATHER_STATE_UUID:
            return encode_state_for_test(redcon=self.current_redcon, battery_mv=3300)
        return encode_measurement_for_test(
            temperature_c=20.0,
            pressure_kpa=100.0,
            humidity_percent=40.0,
            battery_mv=3300,
        )

    async def start_notify(self, uuid: str, handler: Any) -> None:
        self.notifications[uuid] = handler

    async def write_gatt_char(self, uuid: str, payload: bytes, *, response: bool) -> None:
        self.writes.append((uuid, payload, response))
        target_redcon = payload[1]
        self.current_redcon = target_redcon
        self.notifications[WEATHER_STATE_UUID](
            WEATHER_STATE_UUID,
            encode_state_for_test(
                redcon=target_redcon,
                bme280_valid=target_redcon == REDCON_ACTIVE,
                battery_mv=3300,
            ),
        )
        if target_redcon == REDCON_ACTIVE:
            self.notifications[WEATHER_MEASUREMENT_UUID](
                WEATHER_MEASUREMENT_UUID,
                encode_measurement_for_test(
                    temperature_c=21.0,
                    pressure_kpa=101.0,
                    humidity_percent=41.0,
                    battery_mv=3300,
                ),
            )


class NoNotifyOnWriteFakeClient(FakeClient):
    async def write_gatt_char(self, uuid: str, payload: bytes, *, response: bool) -> None:
        self.writes.append((uuid, payload, response))
        self.current_redcon = payload[1]


class StaleNoNotifyOnWriteFakeClient(FakeClient):
    async def write_gatt_char(self, uuid: str, payload: bytes, *, response: bool) -> None:
        self.writes.append((uuid, payload, response))


class DisconnectRaisesFakeClient(FakeClient):
    async def disconnect(self) -> None:
        raise EOFError()


class FailFirstConnectFakeClient(FakeClient):
    failures_remaining = 1

    async def connect(self) -> None:
        if FailFirstConnectFakeClient.failures_remaining:
            FailFirstConnectFakeClient.failures_remaining -= 1
            self.trigger_unexpected_disconnect()
            raise RuntimeError("failed to discover services, device disconnected")
        await super().connect()


class WeatherBleDebugCliTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeScanner.instances.clear()
        FakeClient.instances.clear()
        FailFirstConnectFakeClient.failures_remaining = 1

    def test_format_event_uses_key_value_fields(self) -> None:
        line = format_event("adv", name="weather-1", rssi=-42, empty=None)

        self.assertIn(" adv ", line)
        self.assertIn("name=weather-1", line)
        self.assertIn("rssi=-42", line)
        self.assertNotIn("empty=", line)

    def test_discover_target_matches_name_and_service_uuid(self) -> None:
        async def exercise() -> tuple[object, list[str], bool]:
            lines: list[str] = []
            target = await discover_target(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
            )
            return target.device, lines, FakeScanner.instances[0].stopped

        device, lines, stopped = asyncio.run(exercise())

        self.assertIsInstance(device, FakeDevice)
        self.assertTrue(stopped)
        self.assertTrue(any("adv " in line and "service=1" in line for line in lines))

    def test_platform_detection_selects_corebluetooth_on_macos(self) -> None:
        stack = detect_ble_stack(sys_platform="darwin", adapter="hci9")

        self.assertEqual(stack.backend, "corebluetooth")
        self.assertEqual(stack.os, "macos")
        self.assertEqual(stack.scanner_kwargs, {})
        self.assertEqual(stack.client_kwargs, {})

    def test_platform_detection_selects_bluez_on_linux(self) -> None:
        stack = detect_ble_stack(sys_platform="linux", adapter="hci1")

        self.assertEqual(stack.backend, "bluez")
        self.assertEqual(stack.os, "linux")
        self.assertEqual(stack.scanner_kwargs, {"adapter": "hci1"})
        self.assertEqual(stack.client_kwargs, {"adapter": "hci1"})

    def test_linux_stack_passes_bluez_adapter_to_scanner(self) -> None:
        async def exercise() -> dict[str, Any]:
            target = await discover_target(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lambda _line: None),
                scanner_factory=FakeScanner,
                stack=detect_ble_stack(sys_platform="linux", adapter="hci1"),
            )
            self.assertIsInstance(target.device, FakeDevice)
            return FakeScanner.instances[0].kwargs

        kwargs = asyncio.run(exercise())

        self.assertEqual(kwargs, {"adapter": "hci1"})

    def test_scan_emits_summary(self) -> None:
        async def exercise() -> list[str]:
            lines: list[str] = []
            await scan(
                name="weather-1",
                timeout=0,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
            )
            return lines

        lines = asyncio.run(exercise())

        self.assertTrue(any("adv " in line for line in lines))
        self.assertTrue(any("summary " in line and "advCount=1" in line for line in lines))

    def test_wake_and_sleep_write_expected_commands(self) -> None:
        async def exercise() -> tuple[list[str], FakeClient]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=FakeClient,
            )
            await session.connect()
            await session.wake(deadline=1.0)
            await session.sleep(deadline=1.0)
            await session.disconnect()
            return lines, FakeClient.instances[0]

        lines, client = asyncio.run(exercise())

        self.assertIsInstance(client.device, FakeDevice)
        self.assertEqual(
            client.writes,
            [
                (WEATHER_COMMAND_UUID, encode_command(REDCON_ACTIVE), True),
                (WEATHER_COMMAND_UUID, encode_command(REDCON_IDLE), True),
            ],
        )
        self.assertEqual(client.timeout, 0.1)
        self.assertEqual(client.services_filter, [WEATHER_SERVICE_UUID])
        self.assertEqual(client.client_kwargs, {})
        self.assertTrue(any("connected " in line and "connectMs=" in line for line in lines))
        self.assertTrue(any("connected " in line and "backend=" in line for line in lines))
        self.assertTrue(any("services " in line and "servicesMs=" in line for line in lines))
        self.assertTrue(any("wake-ok" in line for line in lines))
        self.assertTrue(any("sleep-ok" in line for line in lines))
        self.assertTrue(any("disconnect " in line and "unexpected=0" in line for line in lines))

    def test_linux_stack_passes_bluez_adapter_to_client(self) -> None:
        async def exercise() -> FakeClient:
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lambda _line: None),
                scanner_factory=FakeScanner,
                client_factory=FakeClient,
                stack=detect_ble_stack(sys_platform="linux", adapter="hci1"),
            )
            await session.connect()
            await session.disconnect()
            return FakeClient.instances[0]

        client = asyncio.run(exercise())

        self.assertEqual(client.client_kwargs, {"adapter": "hci1"})

    def test_disconnect_cleanup_error_does_not_raise(self) -> None:
        async def exercise() -> list[str]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=DisconnectRaisesFakeClient,
            )
            await session.connect()
            await session.disconnect()
            return lines

        lines = asyncio.run(exercise())

        self.assertTrue(
            any("disconnect " in line and "unexpected=0" in line and "error=EOFError" in line for line in lines)
        )

    def test_connect_retries_initial_service_discovery_failure(self) -> None:
        async def exercise() -> tuple[list[str], list[FailFirstConnectFakeClient]]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=FailFirstConnectFakeClient,
                connect_attempts=2,
            )
            await session.connect()
            await session.disconnect()
            return lines, FailFirstConnectFakeClient.instances

        lines, clients = asyncio.run(exercise())

        self.assertEqual(len(clients), 2)
        self.assertTrue(any("connect-retry " in line and "attempt=1" in line for line in lines))
        self.assertTrue(any("connected " in line and "attempt=2" in line for line in lines))
        self.assertFalse(any("disconnect " in line and "unexpected=1" in line for line in lines))

    def test_unexpected_disconnect_fails_idle_observation(self) -> None:
        async def exercise() -> tuple[str, str, list[str]]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=FakeClient,
            )
            await session.connect()
            client = FakeClient.instances[0]
            asyncio.get_running_loop().call_soon(client.trigger_unexpected_disconnect)
            try:
                await session.observe(1.0, stage="idle")
            except DebugError as err:
                await session.disconnect(emit=False)
                return err.stage, str(err), lines
            raise AssertionError("expected idle observation to fail")

        stage, message, lines = asyncio.run(exercise())

        self.assertEqual(stage, "idle")
        self.assertEqual(message, "unexpected disconnect")
        self.assertTrue(any("disconnect " in line and "unexpected=1" in line for line in lines))

    def test_cleanup_after_unexpected_disconnect_does_not_emit_expected_disconnect(self) -> None:
        async def exercise() -> list[str]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=FakeClient,
            )
            await session.connect()
            FakeClient.instances[0].trigger_unexpected_disconnect()
            await asyncio.sleep(0)
            await session.disconnect()
            return lines

        lines = asyncio.run(exercise())

        self.assertTrue(any("disconnect " in line and "unexpected=1" in line for line in lines))
        self.assertFalse(any("disconnect " in line and "unexpected=0" in line for line in lines))

    def test_wake_deadline_expires_without_measurement(self) -> None:
        async def exercise() -> tuple[str, str]:
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lambda _line: None),
                scanner_factory=FakeScanner,
                client_factory=FakeClient,
            )
            await session.connect()
            try:
                await session.wait_for_measurement_after(session.cadence.count, deadline=0.001)
            except DebugError as err:
                await session.disconnect()
                return err.stage, str(err)
            raise AssertionError("expected measurement wait to fail")

        stage, message = asyncio.run(exercise())

        self.assertEqual(stage, "wake")
        self.assertIn("measurement deadline expired", message)

    def test_sleep_accepts_direct_state_read_after_missed_notification(self) -> None:
        async def exercise() -> list[str]:
            lines: list[str] = []
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lines.append),
                scanner_factory=FakeScanner,
                client_factory=NoNotifyOnWriteFakeClient,
            )
            await session.connect()
            NoNotifyOnWriteFakeClient.instances[0].current_redcon = REDCON_ACTIVE
            await session.sleep(deadline=1.0)
            await session.disconnect()
            return lines

        lines = asyncio.run(exercise())

        self.assertTrue(any("sleep-ok" in line for line in lines))

    def test_sleep_waits_for_fresh_state_after_command(self) -> None:
        async def exercise() -> tuple[str, str]:
            session = WeatherBleDebugClient(
                name="weather-1",
                timeout=0.1,
                sink=EventSink(lambda _line: None),
                scanner_factory=FakeScanner,
                client_factory=StaleNoNotifyOnWriteFakeClient,
            )
            await session.connect()
            StaleNoNotifyOnWriteFakeClient.instances[0].current_redcon = REDCON_ACTIVE
            try:
                await session.sleep(deadline=0.001)
            except DebugError as err:
                await session.disconnect()
                return err.stage, str(err)
            raise AssertionError("expected sleep wait to fail")

        stage, message = asyncio.run(exercise())

        self.assertEqual(stage, "sleep")
        self.assertIn("state 4 deadline expired", message)

    def test_measurement_cadence_detects_one_second_stream(self) -> None:
        cadence = MeasurementCadence()
        cadence.record(10.0)
        cadence.record(11.0)
        cadence.record(12.1)

        self.assertTrue(cadence.stable())
        self.assertEqual(cadence.summary_fields()["measurementCount"], 3)
        self.assertEqual(cadence.summary_fields()["maxIntervalMs"], 1100)


if __name__ == "__main__":
    unittest.main()
