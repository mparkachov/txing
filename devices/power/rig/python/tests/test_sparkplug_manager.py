from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from rig.connectivity_protocol import (
    CONTROL_EVENTUAL,
    INVENTORY_TOPIC,
    PRESENCE_ONLINE,
    ConnectivityInventory,
    ConnectivityState,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    TRANSPORT_BLE_GATT,
)
from rig.local_pubsub import InMemoryLocalPubSub
from rig.sparkplug import (
    build_device_death_payload,
    build_device_topic,
    decode_payload,
)
from rig.thing_registry import ThingRegistration
from power_rig.sparkplug_manager import (
    PowerSparkplugConfig,
    PowerSparkplugManager,
)


class FakeConnection:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def connect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        del timeout_seconds
        self.published.append((topic, payload))

    async def subscribe(
        self,
        topic: str,
        callback: object,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        del topic, callback, timeout_seconds

    async def disconnect(self, *, timeout_seconds: float | None = None) -> None:
        del timeout_seconds


class FakeDeviceSession:
    instances: list["FakeDeviceSession"] = []

    def __init__(
        self,
        config: object,
        *,
        thing_name: str,
        aws_runtime: object,
        **_kwargs: object,
    ) -> None:
        del aws_runtime
        self.config = config
        self.thing_name = thing_name
        self.connected = False
        self.born = False
        self.published: list[tuple[str, bytes]] = []
        self._seq = 0
        FakeDeviceSession.instances.append(self)

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    async def publish_birth_payload(self, payload_factory: object) -> None:
        if self.connected and self.born:
            return
        self.connected = True
        self.born = True
        topic = build_device_topic(
            self.config.sparkplug_group_id,
            "DBIRTH",
            self.config.sparkplug_edge_node_id,
            self.thing_name,
        )
        self.published.append((topic, payload_factory(self._next_seq())))

    async def publish_data_payload(self, payload_factory: object) -> bool:
        if not self.connected or not self.born:
            return False
        topic = build_device_topic(
            self.config.sparkplug_group_id,
            "DDATA",
            self.config.sparkplug_edge_node_id,
            self.thing_name,
        )
        self.published.append((topic, payload_factory(self._next_seq())))
        return True

    async def teardown(self, *, explicit_death: bool) -> None:
        if explicit_death:
            topic = build_device_topic(
                self.config.sparkplug_group_id,
                "DDEATH",
                self.config.sparkplug_edge_node_id,
                self.thing_name,
            )
            self.published.append((topic, build_device_death_payload(seq=self._next_seq())))
        self.connected = False
        self.born = False


def registration(thing_name: str) -> ThingRegistration:
    return ThingRegistration(
        thing_name=thing_name,
        thing_type="power",
        name="power",
        short_id=thing_name,
        town_name="town",
        rig_name="server",
        capabilities_set=("sparkplug",),
    )


def power_state(*, connected: bool, redcon: int = 4, observed_at_ms: int = 1714380000000) -> ConnectivityState:
    return ConnectivityState(
        adapter_id="power-ble-main",
        thing_name="power-1",
        transport=TRANSPORT_BLE_GATT,
        native_identity={"bleLocalName": "power-1", "bleConnected": connected},
        presence=PRESENCE_ONLINE,
        control_availability=CONTROL_EVENTUAL,
        power=redcon < 4,
        sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
        battery_mv=3512,
        observed_at_ms=observed_at_ms,
    )


class PowerSparkplugManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDeviceSession.instances = []

    def test_repeated_connected_redcon_four_reports_publish_repeated_ddata(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            manager = PowerSparkplugManager(
                PowerSparkplugConfig(
                    endpoint="endpoint",
                    aws_region="eu-central-1",
                    rig_name="server",
                    sparkplug_group_id="town",
                    sparkplug_edge_node_id="server",
                ),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("power-1")])
            await manager.connect()
            state = power_state(connected=True)
            await manager.apply_connectivity_state(state)
            await manager.apply_connectivity_state(
                replace(state, observed_at_ms=state.observed_at_ms + 60_000, seq=1)
            )
            await manager.apply_connectivity_state(
                replace(state, observed_at_ms=state.observed_at_ms + 120_000, seq=2)
            )
            return FakeDeviceSession.instances[0].published

        published = asyncio.run(exercise())

        self.assertEqual(
            [topic for topic, _payload in published],
            [
                "spBv1.0/town/DBIRTH/server/power-1",
                "spBv1.0/town/DDATA/server/power-1",
                "spBv1.0/town/DDATA/server/power-1",
            ],
        )
        metrics = {metric.name: metric for metric in decode_payload(published[-1][1]).metrics}
        self.assertEqual(metrics["redcon"].int_value, 4)
        self.assertEqual(metrics["batteryMv"].int_value, 3512)

    def test_repeated_disconnected_idle_reports_do_not_publish_ddata(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            manager = PowerSparkplugManager(
                PowerSparkplugConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
                session_factory=FakeDeviceSession,
            )
            await manager.set_registrations([registration("power-1")])
            await manager.connect()
            state = power_state(connected=False)
            await manager.apply_connectivity_state(state)
            await manager.apply_connectivity_state(
                replace(state, observed_at_ms=state.observed_at_ms + 60_000, seq=1)
            )
            return FakeDeviceSession.instances[0].published

        published = asyncio.run(exercise())

        self.assertEqual(
            [topic for topic, _payload in published],
            ["spBv1.0/town/DBIRTH/server/power-1"],
        )

    def test_publishes_power_inventory(self) -> None:
        async def exercise() -> ConnectivityInventory:
            bus = InMemoryLocalPubSub()
            published: list[bytes] = []
            await bus.subscribe(INVENTORY_TOPIC, lambda _topic, payload: published.append(payload))
            manager = PowerSparkplugManager(
                PowerSparkplugConfig(endpoint="endpoint", aws_region="eu-central-1"),
                bus=bus,
                aws_runtime=object(),
                connection_factory=FakeConnection,
            )
            await manager.set_registrations([registration("power-1")])
            return ConnectivityInventory.from_payload(published[-1])

        inventory = asyncio.run(exercise())

        self.assertEqual(inventory.adapter_id, "power-sparkplug-manager")
        self.assertEqual([device.thing_name for device in inventory.devices], ["power-1"])
        self.assertEqual(inventory.devices[0].transport, TRANSPORT_BLE_GATT)
        self.assertEqual(inventory.devices[0].sleep_model, SLEEP_MODEL_BLE_CONNECTED_IDLE)


if __name__ == "__main__":
    unittest.main()
