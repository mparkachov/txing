from __future__ import annotations

import json
import unittest

from rig.capability_protocol import (
    CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX,
    CAPABILITY_COMMAND_TOPIC_PREFIX,
    CAPABILITY_STATE_TOPIC_PREFIX,
    CapabilityCommand,
    CapabilityCommandResult,
    CapabilityInventory,
    CapabilityInventoryDevice,
    CapabilityProtocolError,
    CapabilityState,
    SparkplugMetricValue,
    build_capability_command_result_topic,
    build_capability_command_topic,
    build_capability_state_topic,
    parse_capability_command_result_topic,
    parse_capability_command_topic,
    parse_capability_state_topic,
)


class CapabilityProtocolTests(unittest.TestCase):
    def test_topics_use_v2_capability_namespace(self) -> None:
        adapter_id = "dev.txing.rig.BleConnectivity"
        self.assertEqual(
            build_capability_state_topic("power-1", adapter_id),
            f"dev/txing/rig/v2/capability/state/power-1/{adapter_id}",
        )
        self.assertEqual(
            build_capability_command_topic("power-1"),
            "dev/txing/rig/v2/capability/command/power-1",
        )
        self.assertEqual(
            build_capability_command_result_topic("power-1", adapter_id),
            f"dev/txing/rig/v2/capability/command-result/power-1/{adapter_id}",
        )
        self.assertEqual(
            parse_capability_state_topic(f"{CAPABILITY_STATE_TOPIC_PREFIX}/power-1/{adapter_id}"),
            ("power-1", adapter_id),
        )
        self.assertEqual(parse_capability_command_topic(f"{CAPABILITY_COMMAND_TOPIC_PREFIX}/power-1"), "power-1")
        self.assertEqual(
            parse_capability_command_result_topic(
                f"{CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX}/power-1/{adapter_id}"
            ),
            ("power-1", adapter_id),
        )

    def test_inventory_round_trips_capability_rules(self) -> None:
        inventory = CapabilityInventory(
            manager_id="rig-sparkplug-manager",
            devices=(
                CapabilityInventoryDevice(
                    thing_name="power-1",
                    thing_type="power",
                    capabilities=("sparkplug", "ble", "power"),
                    redcon_command_levels=(4, 3),
                    redcon_rules={
                        4: ("sparkplug", "ble"),
                        3: ("sparkplug", "ble", "power"),
                    },
                ),
            ),
            seq=7,
            issued_at_ms=1714380000000,
        )

        decoded = CapabilityInventory.from_payload(inventory.to_json())

        self.assertEqual(decoded, inventory)
        payload = json.loads(inventory.to_json())
        self.assertEqual(payload["schemaVersion"], "2.0")
        self.assertEqual(payload["devices"][0]["redconRules"]["3"], ["sparkplug", "ble", "power"])

    def test_state_command_and_result_validate_redcon(self) -> None:
        state = CapabilityState(
            adapter_id="dev.txing.rig.BleConnectivity",
            thing_name="power-1",
            capabilities={"sparkplug": True, "ble": True, "power": False},
            metrics={"batteryMv": SparkplugMetricValue("Int32", 3970)},
            observed_at_ms=1714380000000,
            seq=3,
        )
        self.assertEqual(CapabilityState.from_payload(state.to_json()), state)

        command = CapabilityCommand(
            command_id="cmd-1",
            thing_name="power-1",
            redcon=3,
            reason="operator",
            issued_at_ms=1714380000001,
        )
        self.assertEqual(CapabilityCommand.from_payload(command.to_json()), command)
        self.assertEqual(json.loads(command.to_json())["target"], {"redcon": 3})

        result = CapabilityCommandResult(
            adapter_id="dev.txing.rig.BleConnectivity",
            command_id="cmd-1",
            thing_name="power-1",
            status="succeeded",
            redcon=3,
            message=None,
            observed_at_ms=1714380000002,
        )
        self.assertEqual(CapabilityCommandResult.from_payload(result.to_json()), result)

        payload = json.loads(command.to_json())
        payload["target"] = {"power": True}
        with self.assertRaises(CapabilityProtocolError):
            CapabilityCommand.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
