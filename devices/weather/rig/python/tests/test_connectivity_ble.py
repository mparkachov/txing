from __future__ import annotations

import asyncio
import struct
import unittest
from dataclasses import dataclass

from rig.connectivity_protocol import (
    COMMAND_ACCEPTED,
    COMMAND_SUCCEEDED,
    INVENTORY_TOPIC,
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
from weather_rig.connectivity_ble import (
    MEASUREMENT_STRUCT,
    PROTOCOL_VERSION,
    STATE_FLAG_BME280_VALID,
    STATE_STRUCT,
    WEATHER_COMMAND_UUID,
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
    def __init__(self, _device: FakeDevice) -> None:
        self.is_connected = True
        self.writes: list[tuple[str, bytes, bool]] = []
        self.notifications: dict[str, object] = {}

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
    def test_connects_by_thing_name_and_publishes_online_idle_state(self) -> None:
        async def exercise() -> tuple[ConnectivityState, FakeClient]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []
            await bus.subscribe(build_state_topic("weather-1"), lambda _t, p: received.append(p))
            client_holder: list[FakeClient] = []

            async def discover(**_kwargs: object) -> list[FakeDevice]:
                return [FakeDevice("weather-1")]

            def client_factory(device: FakeDevice) -> FakeClient:
                client = FakeClient(device)
                client_holder.append(client)
                return client

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                scanner_factory=discover,
                client_factory=client_factory,
            )
            task = asyncio.create_task(session.run())
            while len(received) < 2:
                await asyncio.sleep(0)
            session.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return ConnectivityState.from_payload(received[1]), client_holder[0]

        state, client = asyncio.run(exercise())

        self.assertEqual(state.thing_name, "weather-1")
        self.assertEqual(state.transport, TRANSPORT_BLE_GATT)
        self.assertEqual(state.sleep_model, SLEEP_MODEL_BLE_CONNECTED_IDLE)
        self.assertTrue(state.reachable)
        self.assertFalse(state.power)
        self.assertIn("weather-1", state.native_identity["bleLocalName"])
        self.assertEqual(client.writes, [])

    def test_command_write_publishes_succeeded_result(self) -> None:
        async def exercise() -> tuple[list[ConnectivityCommandResult], list[tuple[str, bytes, bool]]]:
            bus = InMemoryLocalPubSub()
            results: list[ConnectivityCommandResult] = []
            await bus.subscribe(
                build_command_result_topic("weather-1"),
                lambda _t, p: results.append(ConnectivityCommandResult.from_payload(p)),
            )
            client_holder: list[FakeClient] = []

            async def discover(**_kwargs: object) -> list[FakeDevice]:
                return [FakeDevice("weather-1")]

            def client_factory(device: FakeDevice) -> FakeClient:
                client = FakeClient(device)
                client_holder.append(client)
                return client

            session = WeatherBleDeviceSession(
                thing_name="weather-1",
                config=WeatherBleConfig(scan_timeout=0.01, reconnect_delay=0.01),
                bus=bus,
                scanner_factory=discover,
                client_factory=client_factory,
            )
            task = asyncio.create_task(session.run())
            while not client_holder:
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
            return results, client_holder[0].writes

        results, writes = asyncio.run(exercise())

        self.assertEqual(results[0].status, COMMAND_SUCCEEDED)
        self.assertEqual(writes[0], (WEATHER_COMMAND_UUID, encode_redcon_command(3), True))


class WeatherConnectivityBleServiceTests(unittest.TestCase):
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
                ).to_json().encode(),
            )
            await service._stop_all_sessions()
            return list(service._sessions), results

        sessions, results = asyncio.run(exercise())

        self.assertEqual(sessions, [])
        self.assertEqual(results[0].status, COMMAND_ACCEPTED)

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
