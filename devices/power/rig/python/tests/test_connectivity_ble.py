from __future__ import annotations

import asyncio
import unittest

from rig.capability_protocol import (
    CapabilityState,
    build_capability_state_topic,
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
        async def exercise() -> CapabilityState:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(
                build_capability_state_topic("power-1", "power-ble-main"),
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
            return CapabilityState.from_payload(published[0])

        state = asyncio.run(exercise())

        self.assertEqual(
            state.capabilities,
            {"sparkplug": True, "ble": True, "power": False},
        )
        self.assertEqual(state.metrics["batteryMv"].datatype, "Int32")
        self.assertEqual(state.metrics["batteryMv"].value, 3512)
        self.assertEqual(state.metrics["bleConnected"].datatype, "Boolean")
        self.assertTrue(state.metrics["bleConnected"].value)

    def test_fresh_power_presence_enters_connected_idle_without_command(self) -> None:
        class Device:
            address = "AA:BB:CC:DD:EE:FF"
            seq = 7

        async def exercise() -> tuple[bool, CapabilityState]:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(
                build_capability_state_topic("power-1", "power-ble-main"),
                lambda _topic, payload: published.append(payload),
            )
            session = PowerBleDeviceSession(
                thing_name="power-1",
                config=PowerBleConfig(),
                bus=bus,
            )
            should_connect = await session._run_advertising_presence(Device())
            return should_connect, CapabilityState.from_payload(published[0])

        should_connect, state = asyncio.run(exercise())

        self.assertTrue(should_connect)
        self.assertEqual(
            state.capabilities,
            {"sparkplug": True, "ble": True, "power": False},
        )
        self.assertFalse(state.metrics["bleConnected"].value)


if __name__ == "__main__":
    unittest.main()
