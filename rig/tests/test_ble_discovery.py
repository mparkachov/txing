from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass

from rig.ble_discovery import BleDiscoveryService
from rig.connectivity_protocol import (
    BLE_ADVERTISEMENT_TOPIC_PREFIX,
    BleAdvertisement,
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


if __name__ == "__main__":
    unittest.main()
