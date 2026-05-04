from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass

from rig.ble_discovery import BleDiscoveryService
from rig.connectivity_protocol import (
    BLE_ADVERTISEMENT_TOPIC_PREFIX,
    BLE_SCAN_CONTROL_TOPIC,
    BLE_SCAN_PAUSE,
    BLE_SCAN_RESUME,
    BleAdvertisement,
    BleScanControl,
    ConnectivityDeviceConfig,
    ConnectivityInventory,
    SLEEP_MODEL_BLE_CONNECTED_IDLE,
    SLEEP_MODEL_BLE_RENDEZVOUS,
    TRANSPORT_BLE_GATT,
)
from rig.local_pubsub import InMemoryLocalPubSub


@dataclass(slots=True)
class FakeDevice:
    address: str = "AA:BB:CC:DD:EE:FF"
    name: str = "weather-1"


@dataclass(slots=True)
class FakeAdvertisementData:
    local_name: str = "weather-1"
    rssi: int = -54
    service_uuids: list[str] | None = None
    manufacturer_data: dict[int, bytes] | None = None
    service_data: dict[str, bytes] | None = None
    tx_power: int = 3

    def __post_init__(self) -> None:
        if self.service_uuids is None:
            self.service_uuids = ["f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"]
        if self.manufacturer_data is None:
            self.manufacturer_data = {0xFFFF: b"TX\x01"}
        if self.service_data is None:
            self.service_data = {"f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100": b"\x01"}


class BleDiscoveryServiceTests(unittest.TestCase):
    def test_publishes_shared_ble_advertisement_payload(self) -> None:
        async def exercise() -> tuple[BleAdvertisement, bool]:
            bus = InMemoryLocalPubSub()
            payloads: list[bytes] = []
            scanners: list[FakeScanner] = []

            await bus.subscribe(
                f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                lambda _topic, payload: payloads.append(payload),
            )

            class FakeScanner:
                def __init__(self, *, detection_callback: object, **_kwargs: object) -> None:
                    self.detection_callback = detection_callback
                    self.stopped = False
                    scanners.append(self)

                async def start(self) -> None:
                    self.detection_callback(FakeDevice(), FakeAdvertisementData())  # type: ignore[misc]

                async def stop(self) -> None:
                    self.stopped = True

            service = BleDiscoveryService(
                bus=bus,
                adapter_id="shared-ble-scanner",
                publish_all=True,
                scanner_factory=FakeScanner,
            )
            task = asyncio.create_task(service.run())
            while not payloads:
                await asyncio.sleep(0)
            service.stop()
            await task
            return BleAdvertisement.from_payload(payloads[0]), scanners[0].stopped

        advertisement, stopped = asyncio.run(exercise())

        self.assertTrue(stopped)
        self.assertEqual(advertisement.adapter_id, "shared-ble-scanner")
        self.assertEqual(advertisement.address, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(advertisement.name, "weather-1")
        self.assertEqual(advertisement.rssi, -54)
        self.assertEqual(advertisement.manufacturer_data["65535"], "545801")
        self.assertEqual(
            advertisement.service_data["f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"],
            "01",
        )

    def test_ignores_advertisements_before_inventory_targets_are_known(self) -> None:
        async def exercise() -> int:
            bus = InMemoryLocalPubSub()
            payloads: list[bytes] = []
            await bus.subscribe(
                f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                lambda _topic, payload: payloads.append(payload),
            )
            service = BleDiscoveryService(bus=bus)
            service._loop = asyncio.get_running_loop()
            await service._publish_detection(
                FakeDevice(name="keyboard"),
                FakeAdvertisementData(
                    local_name="keyboard",
                    service_uuids=["00001812-0000-1000-8000-00805f9b34fb"],
                    manufacturer_data={76: b"\x01"},
                    service_data={},
                ),
            )
            return len(payloads)

        self.assertEqual(asyncio.run(exercise()), 0)

    def test_publishes_matching_inventory_target(self) -> None:
        async def exercise() -> int:
            bus = InMemoryLocalPubSub()
            payloads: list[bytes] = []
            await bus.subscribe(
                f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                lambda _topic, payload: payloads.append(payload),
            )
            service = BleDiscoveryService(bus=bus)
            service._loop = asyncio.get_running_loop()
            service._target_names.add("weather-1")
            await service._publish_detection(FakeDevice(), FakeAdvertisementData())
            return len(payloads)

        self.assertEqual(asyncio.run(exercise()), 1)

    def test_scan_control_pauses_and_resumes_shared_scanner(self) -> None:
        async def exercise() -> tuple[int, int]:
            bus = InMemoryLocalPubSub()
            scanners: list[FakeScanner] = []

            class FakeScanner:
                def __init__(self, *, detection_callback: object, **_kwargs: object) -> None:
                    del detection_callback
                    self.started = False
                    self.stopped = False
                    scanners.append(self)

                async def start(self) -> None:
                    self.started = True

                async def stop(self) -> None:
                    self.stopped = True

            service = BleDiscoveryService(bus=bus, scanner_factory=FakeScanner)
            task = asyncio.create_task(service.run())
            while not scanners or not scanners[0].started:
                await asyncio.sleep(0)
            await bus.publish(
                BLE_SCAN_CONTROL_TOPIC,
                BleScanControl(
                    adapter_id="weather-ble-main",
                    action=BLE_SCAN_PAUSE,
                    reason="connect:weather-1",
                    observed_at_ms=1000,
                    deadline_ms=9999999999999,
                ).to_json(),
            )
            while not scanners[0].stopped:
                await asyncio.sleep(0)
            await bus.publish(
                BLE_SCAN_CONTROL_TOPIC,
                BleScanControl(
                    adapter_id="weather-ble-main",
                    action=BLE_SCAN_RESUME,
                    reason="connected:weather-1",
                    observed_at_ms=1001,
                ).to_json(),
            )
            while len(scanners) < 2 or not scanners[1].started:
                await asyncio.sleep(0)
            service.stop()
            await task
            return len(scanners), sum(scanner.stopped for scanner in scanners)

        scanner_count, stopped_count = asyncio.run(exercise())

        self.assertEqual(scanner_count, 2)
        self.assertEqual(stopped_count, 2)

    def test_throttles_duplicate_advertisements_by_address(self) -> None:
        async def exercise() -> int:
            bus = InMemoryLocalPubSub()
            payloads: list[bytes] = []
            await bus.subscribe(
                f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                lambda _topic, payload: payloads.append(payload),
            )
            service = BleDiscoveryService(bus=bus, publish_interval=60.0)
            service._loop = asyncio.get_running_loop()
            service._target_names.add("weather-1")
            device = FakeDevice()
            advertisement = FakeAdvertisementData()
            await service._publish_detection(device, advertisement)
            await service._publish_detection(device, advertisement)
            return len(payloads)

        self.assertEqual(asyncio.run(exercise()), 1)

    def test_inventory_targets_are_union_across_adapters(self) -> None:
        async def exercise() -> tuple[int, set[str], set[str]]:
            bus = InMemoryLocalPubSub()
            payloads: list[bytes] = []
            await bus.subscribe(
                f"{BLE_ADVERTISEMENT_TOPIC_PREFIX}/+",
                lambda _topic, payload: payloads.append(payload),
            )
            service = BleDiscoveryService(bus=bus)
            service._loop = asyncio.get_running_loop()
            await service._handle_inventory(
                "",
                ConnectivityInventory(
                    adapter_id="weather-sparkplug-manager",
                    devices=(
                        ConnectivityDeviceConfig(
                            thing_name="weather-1",
                            transport=TRANSPORT_BLE_GATT,
                            native_identity={"bleLocalName": "weather-1"},
                            sleep_model=SLEEP_MODEL_BLE_CONNECTED_IDLE,
                        ),
                    ),
                    seq=1,
                    issued_at_ms=1000,
                ).to_json().encode("utf-8"),
            )
            await service._handle_inventory(
                "",
                ConnectivityInventory(
                    adapter_id="unit-sparkplug-manager",
                    devices=(
                        ConnectivityDeviceConfig(
                            thing_name="unit-1",
                            transport=TRANSPORT_BLE_GATT,
                            native_identity={"bleDeviceId": "aa:bb:cc:dd:ee:ff"},
                            sleep_model=SLEEP_MODEL_BLE_RENDEZVOUS,
                        ),
                    ),
                    seq=1,
                    issued_at_ms=1001,
                ).to_json().encode("utf-8"),
            )

            await service._publish_detection(FakeDevice(), FakeAdvertisementData())
            return len(payloads), service._target_addresses, service._target_names

        publish_count, addresses, names = asyncio.run(exercise())

        self.assertEqual(publish_count, 1)
        self.assertEqual(addresses, {"AA:BB:CC:DD:EE:FF"})
        self.assertEqual(names, {"weather-1", "unit-1"})


if __name__ == "__main__":
    unittest.main()
