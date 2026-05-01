from __future__ import annotations

import asyncio
import unittest

from rig.connectivity_protocol import (
    COMMAND_ACCEPTED,
    INVENTORY_TOPIC,
    ConnectivityCommand,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    SLEEP_MODEL_MATTER_ICD,
    TRANSPORT_BLE_GATT,
    TRANSPORT_MATTER,
    build_command_result_topic,
    build_command_topic,
    build_state_topic,
)
from rig.local_pubsub import InMemoryLocalPubSub
from unit_rig.ble_bridge import BridgeConfig, ShadowState
from unit_rig.connectivity_ble import ConnectivityBleCloudProxy, ConnectivityBleService


class ConnectivityBleCloudProxyTests(unittest.TestCase):
    def test_command_becomes_redcon_update_and_ack(self) -> None:
        async def exercise() -> tuple[int | None, list[bytes]]:
            bus = InMemoryLocalPubSub()
            proxy = ConnectivityBleCloudProxy(adapter_id="ble-main", bus=bus)
            results: list[bytes] = []

            def handler(_topic: str, payload: bytes) -> None:
                results.append(payload)

            await bus.subscribe(build_command_result_topic("unit-1"), handler)
            await proxy.enqueue_command(
                ConnectivityCommand(
                    command_id="cmd-1",
                    thing_name="unit-1",
                    power=True,
                    reason="redcon=3",
                    issued_at_ms=1714380000000,
                )
            )
            updates = await proxy.wait_for_updates(timeout_seconds=0.1)
            return updates[0].command_redcon, results

        target_redcon, results = asyncio.run(exercise())
        self.assertEqual(target_redcon, 3)
        self.assertEqual(len(results), 1)
        self.assertIn(f'"status":"{COMMAND_ACCEPTED}"'.encode("utf-8"), results[0])

    def test_shadow_state_publishes_normalized_ble_state(self) -> None:
        async def exercise() -> ConnectivityState:
            bus = InMemoryLocalPubSub()
            proxy = ConnectivityBleCloudProxy(adapter_id="ble-main", bus=bus)
            received: list[bytes] = []

            def handler(_topic: str, payload: bytes) -> None:
                received.append(payload)

            await bus.subscribe(build_state_topic("unit-1"), handler)
            proxy.set_shadow(
                "unit-1",
                ShadowState(
                    reported_power=False,
                    battery_mv=3795,
                    ble_online=True,
                    thing_name="unit-1",
                ),
            )
            await proxy.publish_state("unit-1")
            return ConnectivityState.from_payload(received[0])

        state = asyncio.run(exercise())
        self.assertEqual(state.transport, TRANSPORT_BLE_GATT)
        self.assertEqual(state.sleep_model, SLEEP_MODEL_BLE_RENDEZVOUS)
        self.assertTrue(state.reachable)
        self.assertFalse(state.power)
        self.assertEqual(state.battery_mv, 3795)


class ConnectivityBleServiceTests(unittest.TestCase):
    def test_duplicate_inventory_does_not_restart_running_fleet(self) -> None:
        async def exercise() -> tuple[bool, bool]:
            service = ConnectivityBleService(
                BridgeConfig(rig_name="rig", sparkplug_group_id="town"),
                bus=InMemoryLocalPubSub(),
            )
            inventory = ConnectivityInventory(
                adapter_id="manager",
                seq=1,
                issued_at_ms=1714380000000,
                devices=(
                    ConnectivityDeviceConfig(
                        thing_name="unit-ble",
                        transport=TRANSPORT_BLE_GATT,
                        native_identity={"bleDeviceId": "AA:BB"},
                        sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
                    ),
                ),
            )

            await service._handle_inventory_message(
                INVENTORY_TOPIC,
                inventory.to_json().encode(),
            )
            first_restart = service._inventory_event.is_set()
            service._inventory_event.clear()

            blocker = asyncio.Event()
            service._fleet_task = asyncio.create_task(blocker.wait())
            await service._handle_inventory_message(
                INVENTORY_TOPIC,
                ConnectivityInventory(
                    adapter_id="manager",
                    seq=2,
                    issued_at_ms=1714380005000,
                    devices=inventory.devices,
                ).to_json().encode(),
            )
            second_restart = service._inventory_event.is_set()
            service._fleet_task.cancel()
            await asyncio.gather(service._fleet_task, return_exceptions=True)
            return first_restart, second_restart

        first_restart, second_restart = asyncio.run(exercise())

        self.assertTrue(first_restart)
        self.assertFalse(second_restart)

    def test_inventory_builds_only_ble_managed_things(self) -> None:
        service = ConnectivityBleService(
            BridgeConfig(rig_name="rig", sparkplug_group_id="town"),
            bus=InMemoryLocalPubSub(),
        )
        inventory = ConnectivityInventory(
            adapter_id="manager",
            seq=1,
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

        managed = service._build_managed_things(inventory)

        self.assertEqual([item.registration.thing_name for item in managed], ["unit-ble"])
        self.assertEqual(managed[0].bridge._shadow.ble_device_id, "AA:BB")


if __name__ == "__main__":
    unittest.main()
