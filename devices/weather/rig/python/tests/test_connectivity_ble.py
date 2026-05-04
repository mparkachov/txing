from __future__ import annotations

import asyncio
import struct
import unittest
from dataclasses import dataclass

from rig.connectivity_protocol import (
    COMMAND_ACCEPTED,
    COMMAND_FAILED,
    COMMAND_SUCCEEDED,
    INVENTORY_TOPIC,
    BleAdvertisement,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    TRANSPORT_BLE_GATT,
    build_command_result_topic,
    build_command_topic,
    build_state_topic,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import utc_timestamp_ms
from weather_rig.connectivity_ble import (
    BleakError,
    MEASUREMENT_STRUCT,
    PROTOCOL_VERSION,
    STATE_FLAG_BME280_VALID,
    STATE_STRUCT,
    WEATHER_COMMAND_UUID,
    WEATHER_MEASUREMENT_UUID,
    WEATHER_SERVICE_UUID,
    WeatherBleConfig,
    WeatherBleDeviceSession,
    WeatherConnectivityBleService,
    encode_redcon_command,
    parse_measurement_report,
    parse_state_report,
)


@dataclass(slots=True)
class FakeDevice:
    name: str
    address: str = "AA:BB:CC:DD:EE:FF"


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, _device: FakeDevice) -> None:
        self.is_connected = True
        self.writes: list[tuple[str, bytes, bool]] = []
        self.notifications: dict[str, object] = {}
        self.instances.append(self)

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def read_gatt_char(self, _uuid: str) -> bytes:
        return STATE_STRUCT.pack(PROTOCOL_VERSION, 4, 0, 3300)

    async def write_gatt_char(self, uuid: str, payload: bytes, *, response: bool) -> None:
        self.writes.append((uuid, payload, response))

    async def start_notify(self, uuid: str, handler: object) -> None:
        self.notifications[uuid] = handler


class FailingClient:
    instances: list[FailingClient] = []

    def __init__(self, _device: FakeDevice) -> None:
        self.is_connected = False
        self.connect_kwargs: dict[str, object] | None = None
        self.disconnect_count = 0
        self.instances.append(self)

    async def connect(self, **kwargs: object) -> None:
        self.connect_kwargs = kwargs
        raise BleakError("failed to discover services, device disconnected")

    async def disconnect(self) -> None:
        self.disconnect_count += 1


class SlowConnectClient:
    instances: list[SlowConnectClient] = []

    def __init__(self, _device: FakeDevice) -> None:
        self.is_connected = False
        self.connect_kwargs: dict[str, object] | None = None
        self.cancelled = False
        self.instances.append(self)

    async def connect(self, **kwargs: object) -> None:
        self.connect_kwargs = kwargs
        try:
            await asyncio.sleep(30.0)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def disconnect(self) -> None:
        self.is_connected = False


class DelayedTimeoutClient:
    instances: list[DelayedTimeoutClient] = []

    def __init__(self, _device: FakeDevice) -> None:
        self.is_connected = False
        self.connect_kwargs: dict[str, object] | None = None
        self.failed = False
        self.instances.append(self)

    async def connect(self, **kwargs: object) -> None:
        self.connect_kwargs = kwargs
        await asyncio.sleep(1.05)
        self.failed = True
        raise TimeoutError

    async def disconnect(self) -> None:
        self.is_connected = False


def _weather_advertisement(
    thing_name: str,
    *,
    address: str = "AA:BB:CC:DD:EE:FF",
    service_uuids: tuple[str, ...] = (WEATHER_SERVICE_UUID,),
    seq: int = 1,
) -> BleAdvertisement:
    return BleAdvertisement(
        adapter_id="shared-ble-scanner",
        address=address,
        name=thing_name,
        service_uuids=service_uuids,
        observed_at_ms=utc_timestamp_ms(),
        seq=seq,
    )


class WeatherBleProtocolTests(unittest.TestCase):
    def test_command_normalizes_redcon_one_and_two_to_three(self) -> None:
        self.assertEqual(encode_redcon_command(1), struct.pack("<BB", PROTOCOL_VERSION, 3))
        self.assertEqual(encode_redcon_command(2), struct.pack("<BB", PROTOCOL_VERSION, 3))
        self.assertEqual(encode_redcon_command(4), struct.pack("<BB", PROTOCOL_VERSION, 4))

    def test_state_and_measurement_payloads_decode(self) -> None:
        state = parse_state_report(
            STATE_STRUCT.pack(PROTOCOL_VERSION, 3, STATE_FLAG_BME280_VALID, 3512)
        )
        measurement = parse_measurement_report(
            MEASUREMENT_STRUCT.pack(PROTOCOL_VERSION, 2163, 100800, 4450, 3512)
        )

        self.assertEqual(state.redcon, 3)
        self.assertEqual(state.battery_mv, 3512)
        self.assertTrue(state.bme280_valid)
        self.assertEqual(measurement.measured_temperature, 21.63)
        self.assertEqual(measurement.measured_pressure, 100.8)
        self.assertEqual(measurement.measured_humidity, 44.5)


class WeatherBleDeviceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.instances.clear()
        FailingClient.instances.clear()
        SlowConnectClient.instances.clear()
        DelayedTimeoutClient.instances.clear()

    def test_matches_by_thing_name_and_publishes_online_idle_state(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return ConnectivityState.from_payload(received[0])

        state = asyncio.run(exercise())

        self.assertEqual(state.thing_name, "weather-1")
        self.assertEqual(state.transport, TRANSPORT_BLE_GATT)
        self.assertEqual(state.sleep_model, SLEEP_MODEL_BLE_CONNECTED_IDLE)
        self.assertTrue(state.reachable)
        self.assertFalse(state.power)
        self.assertIn("weather-1", state.native_identity["bleLocalName"])

    def test_exact_thing_name_is_sufficient_for_discovery(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(
                _weather_advertisement(
                    "weather-1",
                    service_uuids=("0000180f-0000-1000-8000-00805f9b34fb",),
                )
            )
            while not received:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return ConnectivityState.from_payload(received[0])

        state = asyncio.run(exercise())

        self.assertTrue(state.reachable)
        self.assertEqual(state.native_identity["bleAddress"], "AA:BB:CC:DD:EE:FF")

    def test_connected_session_reads_initial_state(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.2, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1", seq=1))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )
            while len(received) < 3:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received[:3]]

        states = asyncio.run(exercise())

        self.assertEqual([state.seq for state in states], [1, 2, 3])
        self.assertTrue(all(state.reachable for state in states))
        self.assertEqual(states[2].battery_mv, 3300)

    def test_connected_session_refreshes_online_state_while_idle(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.2,
                    reconnect_delay=0.01,
                    state_report_interval=0.01,
                ),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1", seq=1))

            async def wait_for_reports() -> None:
                while len(received) < 4:
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait_for_reports(), timeout=1.0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received[:4]]

        states = asyncio.run(exercise())

        self.assertEqual([state.seq for state in states], [1, 2, 3, 4])
        self.assertTrue(all(state.reachable for state in states))
        self.assertIsNone(states[-1].battery_mv)

    def test_idle_advertising_presence_does_not_open_gatt_connection(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.2,
                    reconnect_delay=0.01,
                    state_report_interval=0.01,
                ),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1", seq=1))

            while len(received) < 2:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received]

        states = asyncio.run(exercise())

        self.assertTrue(all(state.reachable for state in states))
        self.assertEqual(FakeClient.instances, [])

    def test_failed_connect_keeps_advertising_presence_without_extra_disconnect(self) -> None:
        async def exercise() -> tuple[list[ConnectivityState], FailingClient]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=30.0),
                bus=bus,
                client_factory=FailingClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )
            while not FailingClient.instances or FailingClient.instances[0].connect_kwargs is None:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received], FailingClient.instances[0]

        with self.assertLogs("weather_rig.connectivity_ble", level="WARNING") as logs:
            states, client = asyncio.run(exercise())

        self.assertEqual(len(states), 1)
        self.assertTrue(states[0].reachable)
        self.assertEqual(client.disconnect_count, 0)
        self.assertEqual(client.connect_kwargs, {"dangerous_use_bleak_cache": True})
        self.assertIn("BleakError", logs.output[0])

    def test_slow_connect_is_limited_by_configured_timeout(self) -> None:
        async def exercise() -> tuple[list[ConnectivityState], SlowConnectClient]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.2,
                    reconnect_delay=30.0,
                    connect_timeout=0.01,
                ),
                bus=bus,
                client_factory=SlowConnectClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )

            async def wait_for_connect_timeout() -> None:
                while not SlowConnectClient.instances or not SlowConnectClient.instances[0].cancelled:
                    await asyncio.sleep(0)

            await asyncio.wait_for(wait_for_connect_timeout(), timeout=1.0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received], SlowConnectClient.instances[0]

        with self.assertLogs("weather_rig.connectivity_ble", level="WARNING") as logs:
            states, client = asyncio.run(exercise())

        self.assertTrue(states[0].reachable)
        self.assertEqual(client.connect_kwargs, {"dangerous_use_bleak_cache": True})
        self.assertTrue(client.cancelled)
        self.assertIn("TimeoutError", "\n".join(logs.output))

    def test_connect_failure_after_advertisement_window_does_not_publish_offline(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.01,
                    reconnect_delay=30.0,
                    connect_timeout=2.0,
                ),
                bus=bus,
                client_factory=DelayedTimeoutClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )

            async def wait_for_timeout() -> None:
                while not DelayedTimeoutClient.instances:
                    await asyncio.sleep(0)
                while not DelayedTimeoutClient.instances[0].failed:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_timeout(), timeout=2.0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received]

        with self.assertLogs("weather_rig.connectivity_ble", level="WARNING") as logs:
            states = asyncio.run(exercise())

        self.assertTrue(states)
        self.assertTrue(all(state.reachable for state in states))
        self.assertIn("TimeoutError", "\n".join(logs.output))

    def test_missing_advertisement_publishes_offline_presence(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=30.0),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            while not received:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return ConnectivityState.from_payload(received[0])

        state = asyncio.run(exercise())

        self.assertFalse(state.reachable)

    def test_advertising_presence_tolerates_missed_scan_timeout(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.01,
                    presence_timeout=0.12,
                    reconnect_delay=30.0,
                    state_report_interval=60.0,
                ),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await asyncio.sleep(0.04)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received]

        states = asyncio.run(exercise())

        self.assertTrue(states)
        self.assertTrue(all(state.reachable for state in states))

    def test_advertising_presence_expires_after_presence_timeout(self) -> None:
        async def exercise() -> list[ConnectivityState]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(
                    scan_timeout=0.01,
                    presence_timeout=0.03,
                    reconnect_delay=30.0,
                    state_report_interval=60.0,
                ),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))

            async def wait_for_offline() -> None:
                while True:
                    states = [ConnectivityState.from_payload(payload) for payload in received]
                    if any(not state.reachable for state in states):
                        return
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait_for_offline(), timeout=1.0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return [ConnectivityState.from_payload(payload) for payload in received]

        states = asyncio.run(exercise())

        self.assertTrue(states[0].reachable)
        self.assertFalse(states[-1].reachable)

    def test_command_writes_gatt_and_publishes_success(self) -> None:
        async def exercise() -> tuple[list[ConnectivityCommandResult], list[tuple[str, bytes, bool]]]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))
            results: list[ConnectivityCommandResult] = []
            await bus.subscribe(
                build_command_result_topic("weather-1"),
                lambda _t, p: results.append(ConnectivityCommandResult.from_payload(p)),
            )

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )
            while not results:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return results, FakeClient.instances[0].writes

        results, writes = asyncio.run(exercise())

        self.assertEqual(results[0].status, COMMAND_SUCCEEDED)
        self.assertEqual(writes, [(WEATHER_COMMAND_UUID, encode_redcon_command(3), True)])

    def test_expired_command_publishes_failed_result_without_gatt_write(self) -> None:
        async def exercise() -> list[ConnectivityCommandResult]:
            bus = InMemoryLocalPubSub()
            results: list[ConnectivityCommandResult] = []
            await bus.subscribe(
                build_command_result_topic("weather-1"),
                lambda _t, p: results.append(ConnectivityCommandResult.from_payload(p)),
            )

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-expired",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                    deadline_ms=utc_timestamp_ms() - 1,
                )
            )
            return results

        results = asyncio.run(exercise())

        self.assertEqual(FakeClient.instances, [])
        self.assertEqual(results[0].status, COMMAND_FAILED)
        self.assertIn("deadline expired", results[0].message or "")

    def test_measurement_notification_publishes_weather(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                client_factory=FakeClient,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(session.run())
            session.observe_advertisement(_weather_advertisement("weather-1"))
            while not received:
                await asyncio.sleep(0)
            await session.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )
            while not FakeClient.instances or WEATHER_MEASUREMENT_UUID not in FakeClient.instances[0].notifications:
                await asyncio.sleep(0)
            handler = FakeClient.instances[0].notifications[WEATHER_MEASUREMENT_UUID]
            handler(WEATHER_MEASUREMENT_UUID, MEASUREMENT_STRUCT.pack(PROTOCOL_VERSION, 2163, 100800, 4450, 3512))  # type: ignore[operator]
            while True:
                states = [ConnectivityState.from_payload(payload) for payload in received]
                weather_states = [state for state in states if state.weather is not None]
                if weather_states:
                    session.stop()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return weather_states[-1]
                await asyncio.sleep(0)

        state = asyncio.run(exercise())

        self.assertTrue(state.reachable)
        self.assertTrue(state.power)
        self.assertIsNotNone(state.weather)
        self.assertEqual(state.weather.measured_temperature, 21.63)
        self.assertEqual(state.weather.measured_pressure, 100.8)
        self.assertEqual(state.weather.measured_humidity, 44.5)


class WeatherConnectivityBleServiceTests(unittest.TestCase):
    def test_start_stop_cancels_sessions_before_closing_subscriptions(self) -> None:
        async def exercise() -> list[str]:
            events: list[str] = []

            @dataclass(slots=True)
            class TrackingSubscription:
                inner: object
                topic: str

                def close(self) -> None:
                    events.append(f"close:{self.topic}")
                    close = getattr(self.inner, "close", None)
                    if callable(close):
                        close()

            class TrackingBus(InMemoryLocalPubSub):
                async def publish(self, topic: str, payload: bytes | str) -> None:
                    events.append(f"publish:{topic}")
                    await super().publish(topic, payload)

                async def subscribe(self, topic: str, handler: object) -> TrackingSubscription:  # type: ignore[override]
                    inner = await super().subscribe(topic, handler)  # type: ignore[arg-type]
                    events.append(f"subscribe:{topic}")
                    return TrackingSubscription(inner=inner, topic=topic)

            class FakeSession:
                def __init__(self, *, thing_name: str, **_kwargs: object) -> None:
                    self.thing_name = thing_name

                async def run(self) -> None:
                    events.append("session-run")
                    try:
                        await asyncio.Future()
                    except asyncio.CancelledError:
                        events.append("session-cancelled")
                        raise

                def stop(self) -> None:
                    events.append("session-stop")

                async def enqueue_command(self, _command: ConnectivityCommand) -> None:
                    raise AssertionError("command routing is not part of this test")

            bus = TrackingBus()
            service = WeatherConnectivityBleService(
                WeatherBleConfig(heartbeat_interval=60.0),
                bus=bus,
                session_factory=FakeSession,  # type: ignore[arg-type]
            )
            task = asyncio.create_task(service.start())
            while sum(event.startswith("subscribe:") for event in events) < 3:
                await asyncio.sleep(0)
            await service._handle_inventory(
                INVENTORY_TOPIC,
                ConnectivityInventory(
                    adapter_id="weather-sparkplug-manager",
                    seq=1,
                    issued_at_ms=1714380000000,
                    devices=(
                        ConnectivityDeviceConfig(
                            thing_name="weather-1",
                            transport=TRANSPORT_BLE_GATT,
                            sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
                            native_identity={"bleLocalName": "weather-1"},
                        ),
                    ),
                ).to_json().encode(),
            )
            while "session-run" not in events:
                await asyncio.sleep(0)
            service.stop()
            await asyncio.wait_for(task, timeout=1.0)
            return events

        events = asyncio.run(exercise())
        first_close = next(
            index for index, event in enumerate(events) if event.startswith("close:")
        )

        self.assertLess(events.index("session-cancelled"), first_close)

    def test_inventory_starts_session_and_command_is_accepted(self) -> None:
        class FakeSession:
            def __init__(self, *, thing_name: str, **_kwargs: object) -> None:
                self.thing_name = thing_name
                self.commands: list[ConnectivityCommand] = []
                self.stopped = False

            async def run(self) -> None:
                await asyncio.Future()

            def stop(self) -> None:
                self.stopped = True

            async def enqueue_command(self, command: ConnectivityCommand) -> None:
                self.commands.append(command)

        async def exercise() -> tuple[list[str], list[ConnectivityCommandResult]]:
            bus = InMemoryLocalPubSub()
            service = WeatherConnectivityBleService(
                WeatherBleConfig(),
                bus=bus,
                session_factory=FakeSession,  # type: ignore[arg-type]
            )
            results: list[ConnectivityCommandResult] = []
            await bus.subscribe(
                build_command_result_topic("weather-1"),
                lambda _t, p: results.append(ConnectivityCommandResult.from_payload(p)),
            )
            inventory = ConnectivityInventory(
                adapter_id="weather-sparkplug-manager",
                seq=1,
                issued_at_ms=1714380000000,
                devices=(
                    ConnectivityDeviceConfig(
                        thing_name="weather-1",
                        transport=TRANSPORT_BLE_GATT,
                        sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
                        native_identity={"bleLocalName": "weather-1"},
                    ),
                ),
            )
            await service._handle_inventory(INVENTORY_TOPIC, inventory.to_json().encode())
            await service._handle_command(
                build_command_topic("weather-1"),
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="weather-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                    seq=9,
                ).to_json().encode(),
            )
            await service._stop_all_sessions()
            return list(service._sessions), results

        sessions, results = asyncio.run(exercise())

        self.assertEqual(sessions, [])
        self.assertEqual(results[0].status, COMMAND_ACCEPTED)
        self.assertEqual(results[0].seq, 9)

    def test_unit_inventory_and_command_are_ignored(self) -> None:
        class FakeSession:
            def __init__(self, *, thing_name: str, **_kwargs: object) -> None:
                self.thing_name = thing_name

            async def run(self) -> None:
                await asyncio.Future()

            def stop(self) -> None:
                return None

            async def enqueue_command(self, _command: ConnectivityCommand) -> None:
                raise AssertionError("unit command must not be routed to weather session")

        async def exercise() -> tuple[list[str], list[ConnectivityCommandResult]]:
            bus = InMemoryLocalPubSub()
            service = WeatherConnectivityBleService(
                WeatherBleConfig(),
                bus=bus,
                session_factory=FakeSession,  # type: ignore[arg-type]
            )
            results: list[ConnectivityCommandResult] = []
            await bus.subscribe(
                build_command_result_topic("unit-1"),
                lambda _t, p: results.append(ConnectivityCommandResult.from_payload(p)),
            )
            await service._handle_inventory(
                INVENTORY_TOPIC,
                ConnectivityInventory(
                    adapter_id="unit-sparkplug-manager",
                    seq=1,
                    issued_at_ms=1714380000000,
                    devices=(
                        ConnectivityDeviceConfig(
                            thing_name="unit-1",
                            transport=TRANSPORT_BLE_GATT,
                            sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
                            native_identity={"bleDeviceId": "AA:BB"},
                        ),
                    ),
                ).to_json().encode(),
            )
            await service._handle_command(
                build_command_topic("unit-1"),
                ConnectivityCommand(
                    command_id="cmd-unit",
                    thing_name="unit-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                ).to_json().encode(),
            )
            return list(service._sessions), results

        sessions, results = asyncio.run(exercise())

        self.assertEqual(sessions, [])
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
