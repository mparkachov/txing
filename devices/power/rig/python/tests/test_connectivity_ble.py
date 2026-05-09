from __future__ import annotations

import asyncio
import unittest

from rig.connectivity_protocol import (
    CONTROL_EVENTUAL,
    PRESENCE_ONLINE,
    ConnectivityState,
    build_state_topic,
)
from rig.local_pubsub import InMemoryLocalPubSub
from power_rig.connectivity_ble import (
    POWER_COMMAND_UUID,
    PROTOCOL_VERSION,
    REDCON_ACTIVE,
    REDCON_IDLE,
    STATE_STRUCT,
    PowerBleConfig,
    PowerBleDeviceSession,
    encode_redcon_command,
    parse_state_report,
)


class PowerConnectivityBleTests(unittest.TestCase):
    def test_command_encoding_and_state_parsing_use_four_byte_power_protocol(self) -> None:
        self.assertEqual(encode_redcon_command(REDCON_IDLE), bytes([PROTOCOL_VERSION, 4]))
        self.assertEqual(encode_redcon_command(REDCON_ACTIVE), bytes([PROTOCOL_VERSION, 3]))
        self.assertEqual(POWER_COMMAND_UUID, "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100")

        state = parse_state_report(STATE_STRUCT.pack(PROTOCOL_VERSION, 4, 3512))

        self.assertEqual(state.redcon, REDCON_IDLE)
        self.assertEqual(state.battery_mv, 3512)

    def test_connected_redcon_four_state_report_publishes_battery_connectivity(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(
                build_state_topic("power-1"),
                lambda _topic, payload: published.append(payload),
            )
            session = PowerBleDeviceSession(
                thing_name="power-1",
                config=PowerBleConfig(),
                bus=bus,
            )
            session._ble_connected = True
            session._ble_address = "AA:BB:CC:DD:EE:FF"
            await session._handle_state_bytes(STATE_STRUCT.pack(PROTOCOL_VERSION, 4, 3512))
            return ConnectivityState.from_payload(published[0])

        state = asyncio.run(exercise())

        self.assertEqual(state.presence, PRESENCE_ONLINE)
        self.assertEqual(state.control_availability, CONTROL_EVENTUAL)
        self.assertFalse(state.power)
        self.assertEqual(state.battery_mv, 3512)
        self.assertIsNone(state.weather)
        self.assertTrue(state.native_identity["bleConnected"])
        self.assertEqual(state.native_identity["bleLocalName"], "power-1")

    def test_fresh_power_presence_enters_connected_idle_without_command(self) -> None:
        class Device:
            address = "AA:BB:CC:DD:EE:FF"
            seq = 7

        async def exercise() -> tuple[bool, ConnectivityState]:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(
                build_state_topic("power-1"),
                lambda _topic, payload: published.append(payload),
            )
            session = PowerBleDeviceSession(
                thing_name="power-1",
                config=PowerBleConfig(),
                bus=bus,
            )
            should_connect = await session._run_advertising_presence(Device())
            return should_connect, ConnectivityState.from_payload(published[0])

        should_connect, state = asyncio.run(exercise())

        self.assertTrue(should_connect)
        self.assertEqual(state.presence, PRESENCE_ONLINE)
        self.assertFalse(state.native_identity["bleConnected"])
        self.assertEqual(state.native_identity["bleAddress"], "AA:BB:CC:DD:EE:FF")


if __name__ == "__main__":
    unittest.main()
