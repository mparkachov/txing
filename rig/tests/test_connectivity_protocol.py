from __future__ import annotations

import json
import unittest

from rig.connectivity_protocol import (
    COMMAND_RESULT_TOPIC_PREFIX,
    COMMAND_TOPIC_PREFIX,
    CONTROL_EVENTUAL,
    ConnectivityCommand,
    ConnectivityCommandResult,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityProtocolError,
    ConnectivityState,
    PRESENCE_ONLINE,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    SLEEP_MODEL_MATTER_ICD,
    STATE_TOPIC_PREFIX,
    TRANSPORT_BLE_GATT,
    TRANSPORT_MATTER,
    build_command_result_topic,
    build_command_topic,
    build_state_topic,
    parse_command_result_topic,
    parse_command_topic,
    parse_state_topic,
)


class ConnectivityProtocolTests(unittest.TestCase):
    def test_topics_use_dev_txing_namespace(self) -> None:
        self.assertEqual(
            build_command_topic("unit-123"),
            "dev/txing/rig/v1/connectivity/command/unit-123",
        )
        self.assertEqual(
            build_state_topic("unit-123"),
            "dev/txing/rig/v1/connectivity/state/unit-123",
        )
        self.assertEqual(
            build_command_result_topic("unit-123"),
            "dev/txing/rig/v1/connectivity/command-result/unit-123",
        )
        self.assertEqual(parse_command_topic(f"{COMMAND_TOPIC_PREFIX}/unit-123"), "unit-123")
        self.assertEqual(parse_state_topic(f"{STATE_TOPIC_PREFIX}/unit-123"), "unit-123")
        self.assertEqual(
            parse_command_result_topic(f"{COMMAND_RESULT_TOPIC_PREFIX}/unit-123"),
            "unit-123",
        )

    def test_state_payload_supports_ble_and_matter_shapes(self) -> None:
        ble_state = ConnectivityState(
            adapter_id="ble-main",
            thing_name="unit-123",
            transport=TRANSPORT_BLE_GATT,
            native_identity={"bleDeviceId": "AA:BB:CC:DD:EE:FF"},
            presence=PRESENCE_ONLINE,
            control_availability=CONTROL_EVENTUAL,
            power=False,
            sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
            battery_mv=3795,
            observed_at_ms=1714380000000,
            seq=8,
        )
        decoded_ble = ConnectivityState.from_payload(ble_state.to_json())
        self.assertEqual(decoded_ble, ble_state)
        self.assertTrue(decoded_ble.reachable)

        matter_state = ConnectivityState.from_payload(
            {
                "schemaVersion": "1.0",
                "adapterId": "matter-main",
                "thingName": "unit-matter",
                "transport": TRANSPORT_MATTER,
                "nativeIdentity": {
                    "matterNodeId": 57,
                    "fabricId": "fabric-1",
                    "endpoints": [1],
                },
                "presence": PRESENCE_ONLINE,
                "controlAvailability": CONTROL_EVENTUAL,
                "power": False,
                "sleepModel": SLEEP_MODEL_MATTER_ICD,
                "batteryMv": None,
                "observedAtMs": 1714380000001,
            }
        )
        self.assertEqual(matter_state.transport, TRANSPORT_MATTER)
        self.assertEqual(matter_state.sleep_model, SLEEP_MODEL_MATTER_ICD)
        self.assertTrue(matter_state.reachable)

    def test_inventory_round_trips_multiple_device_transports(self) -> None:
        inventory = ConnectivityInventory(
            adapter_id="manager",
            seq=3,
            issued_at_ms=1714380000000,
            devices=(
                ConnectivityDeviceConfig(
                    thing_name="unit-ble",
                    transport=TRANSPORT_BLE_GATT,
                    native_identity={"bleDeviceId": "AA:BB"},
                    sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
                ),
                ConnectivityDeviceConfig(
                    thing_name="unit-matter",
                    transport=TRANSPORT_MATTER,
                    native_identity={"matterNodeId": 57},
                    sleep_model=SLEEP_MODEL_MATTER_ICD,
                ),
            ),
        )

        decoded = ConnectivityInventory.from_payload(inventory.to_json())

        self.assertEqual(decoded, inventory)
        self.assertEqual([device.thing_name for device in decoded.devices], ["unit-ble", "unit-matter"])

    def test_command_and_result_validate_schema(self) -> None:
        command = ConnectivityCommand(
            command_id="cmd-1",
            thing_name="unit-123",
            power=True,
            reason="redcon=3",
            issued_at_ms=1714380000000,
            deadline_ms=1714380030000,
            seq=9,
        )

        decoded_command = ConnectivityCommand.from_payload(command.to_json())
        self.assertEqual(decoded_command, command)

        result = ConnectivityCommandResult(
            adapter_id="ble-main",
            command_id="cmd-1",
            thing_name="unit-123",
            status="succeeded",
            message=None,
            observed_at_ms=1714380000001,
        )
        self.assertEqual(ConnectivityCommandResult.from_payload(result.to_json()), result)

        payload = json.loads(command.to_json())
        payload["schemaVersion"] = "2.0"
        with self.assertRaises(ConnectivityProtocolError):
            ConnectivityCommand.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
