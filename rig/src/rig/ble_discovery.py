from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from typing import Any, Callable

try:
    from bleak import BleakScanner
except ImportError:  # pragma: no cover - startup validation covers real deployments
    BleakScanner = None

from rig.connectivity_protocol import (
    INVENTORY_TOPIC,
    TRANSPORT_BLE_GATT,
    BleAdvertisement,
    ConnectivityInventory,
    build_ble_advertisement_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

LOGGER = logging.getLogger("rig.ble_discovery")

DEFAULT_ADAPTER_ID = "shared-ble-scanner"
DEFAULT_SCAN_MODE = "active"
DEFAULT_RESTART_DELAY = 2.0
DEFAULT_PUBLISH_INTERVAL = 2.0


class BleDiscoveryService:
    def __init__(
        self,
        *,
        bus: LocalPubSub,
        adapter_id: str = DEFAULT_ADAPTER_ID,
        scan_mode: str = DEFAULT_SCAN_MODE,
        restart_delay: float = DEFAULT_RESTART_DELAY,
        publish_interval: float = DEFAULT_PUBLISH_INTERVAL,
        publish_all: bool = False,
        scanner_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._bus = bus
        self._adapter_id = adapter_id
        self._scan_mode = scan_mode
        self._restart_delay = restart_delay
        self._publish_interval = publish_interval
        self._publish_all = publish_all
        self._scanner_factory = scanner_factory or _default_scanner_factory
        self._stop_event = asyncio.Event()
        self._publish_tasks: set[asyncio.Task[None]] = set()
        self._last_publish_by_key: dict[str, float] = {}
        self._target_addresses: set[str] = set()
        self._target_names: set[str] = set()
        self._targets_by_adapter_id: dict[str, tuple[set[str], set[str]]] = {}
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        inventory_subscription = await self._bus.subscribe(
            INVENTORY_TOPIC,
            self._handle_inventory,
        )
        try:
            while not self._stop_event.is_set():
                scanner: Any | None = None
                try:
                    scanner = self._scanner_factory(
                        detection_callback=self._handle_detection,
                        scanning_mode=self._scan_mode,
                        bluez={"filters": {"DuplicateData": True}},
                    )
                    await _maybe_await(scanner.start())
                    LOGGER.info("Started shared BLE discovery scanner mode=%s", self._scan_mode)
                    await self._stop_event.wait()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "Shared BLE discovery scanner failed; retrying in %.1f seconds",
                        self._restart_delay,
                    )
                    await _sleep_until_stop(self._stop_event, self._restart_delay)
                finally:
                    if scanner is not None:
                        await _stop_scanner(scanner)
        finally:
            _close_resource(inventory_subscription)
            await self._drain_publish_tasks()

    async def _handle_inventory(self, _topic: str, payload: bytes) -> None:
        try:
            inventory = ConnectivityInventory.from_payload(payload)
        except Exception as err:
            LOGGER.warning("Invalid BLE discovery inventory ignored: %s", err)
            return

        target_addresses: set[str] = set()
        target_names: set[str] = set()
        for device in inventory.devices:
            if device.transport != TRANSPORT_BLE_GATT:
                continue
            target_names.add(device.thing_name)
            ble_device_id = device.native_identity.get("bleDeviceId")
            if isinstance(ble_device_id, str) and ble_device_id.strip():
                target_addresses.add(_normalize_address(ble_device_id))
            ble_local_name = device.native_identity.get("bleLocalName")
            if isinstance(ble_local_name, str) and ble_local_name.strip():
                target_names.add(ble_local_name.strip())

        previous_targets = (self._target_addresses, self._target_names)
        self._targets_by_adapter_id[inventory.adapter_id] = (
            target_addresses,
            target_names,
        )
        self._target_addresses = set()
        self._target_names = set()
        for addresses, names in self._targets_by_adapter_id.values():
            self._target_addresses.update(addresses)
            self._target_names.update(names)
        self._last_publish_by_key = {
            key: value
            for key, value in self._last_publish_by_key.items()
            if key in self._target_addresses or key in self._target_names
        }
        current_targets = (self._target_addresses, self._target_names)
        if previous_targets != current_targets:
            LOGGER.info(
                "Updated shared BLE discovery targets adapters=%s addresses=%d names=%d",
                ",".join(sorted(self._targets_by_adapter_id)),
                len(self._target_addresses),
                len(self._target_names),
            )

    def _handle_detection(self, device: Any, advertisement_data: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._schedule_publish, device, advertisement_data)

    def _schedule_publish(self, device: Any, advertisement_data: Any) -> None:
        task = asyncio.create_task(self._publish_detection(device, advertisement_data))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    async def _publish_detection(self, device: Any, advertisement_data: Any) -> None:
        address = _device_address(device)
        if address is None:
            return
        self._seq = (self._seq + 1) % 2_147_483_647
        advertisement = BleAdvertisement(
            adapter_id=self._adapter_id,
            address=address,
            name=_advertisement_name(device, advertisement_data),
            rssi=_optional_int(getattr(advertisement_data, "rssi", None)),
            service_uuids=tuple(
                str(uuid).lower()
                for uuid in (getattr(advertisement_data, "service_uuids", None) or ())
            ),
            manufacturer_data=_manufacturer_data_payload(
                getattr(advertisement_data, "manufacturer_data", None)
            ),
            service_data=_service_data_payload(
                getattr(advertisement_data, "service_data", None)
            ),
            tx_power=_optional_int(getattr(advertisement_data, "tx_power", None)),
            observed_at_ms=utc_timestamp_ms(),
            seq=self._seq,
        )
        publish_key = self._publish_key(advertisement)
        if not self._publish_all and publish_key is None:
            return
        now = asyncio.get_running_loop().time()
        throttle_key = publish_key or _normalize_address(address)
        last_publish = self._last_publish_by_key.get(throttle_key)
        if (
            last_publish is not None
            and self._publish_interval > 0
            and (now - last_publish) < self._publish_interval
        ):
            return
        self._last_publish_by_key[throttle_key] = now
        await self._bus.publish(
            build_ble_advertisement_topic(address),
            advertisement.to_json(),
        )

    def _publish_key(self, advertisement: BleAdvertisement) -> str | None:
        address = _normalize_address(advertisement.address)
        if address in self._target_addresses:
            return address

        name = advertisement.name
        if name is not None and name in self._target_names:
            return name

        return None

    async def _drain_publish_tasks(self) -> None:
        if not self._publish_tasks:
            return
        await asyncio.gather(*self._publish_tasks, return_exceptions=True)
        self._publish_tasks.clear()


def _default_scanner_factory(**kwargs: Any) -> Any:
    if BleakScanner is None:
        raise RuntimeError("bleak is required for shared BLE discovery")
    return BleakScanner(**kwargs)


async def _maybe_await(result: Any) -> Any:
    if hasattr(result, "__await__"):
        return await result
    return result


async def _stop_scanner(scanner: Any) -> None:
    stop = getattr(scanner, "stop", None)
    if not callable(stop):
        return
    try:
        await _maybe_await(stop())
    except Exception:
        LOGGER.exception("Failed to stop shared BLE discovery scanner cleanly")


def _device_address(device: Any) -> str | None:
    address = getattr(device, "address", None)
    return address.strip() if isinstance(address, str) and address.strip() else None


def _advertisement_name(device: Any, advertisement_data: Any) -> str | None:
    for value in (
        getattr(advertisement_data, "local_name", None),
        getattr(device, "name", None),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def _manufacturer_data_payload(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, payload in value.items():
        if isinstance(key, int):
            key_text = str(key)
        else:
            key_text = str(key).strip()
        if not key_text:
            continue
        result[key_text] = bytes(payload).hex()
    return result


def _service_data_payload(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, payload in value.items():
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        result[key_text] = bytes(payload).hex()
    return result


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def _close_resource(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


async def _sleep_until_stop(stop_event: asyncio.Event, delay: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
    except TimeoutError:
        return


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-ble-discovery",
        description="txing shared BLE advertisement discovery adapter",
    )
    parser.add_argument("--adapter-id", default=os.getenv("BLE_DISCOVERY_ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--scan-mode", default=os.getenv("BLE_DISCOVERY_SCAN_MODE", DEFAULT_SCAN_MODE))
    parser.add_argument("--restart-delay", type=float, default=float(os.getenv("BLE_DISCOVERY_RESTART_DELAY", DEFAULT_RESTART_DELAY)))
    parser.add_argument("--publish-interval", type=float, default=float(os.getenv("BLE_DISCOVERY_PUBLISH_INTERVAL", DEFAULT_PUBLISH_INTERVAL)))
    parser.add_argument("--publish-all", action="store_true", default=os.getenv("BLE_DISCOVERY_PUBLISH_ALL", "").lower() in {"1", "true", "yes"})
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _runner() -> None:
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def _request_shutdown() -> None:
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                break
        bus = GreengrassLocalPubSub()
        service = BleDiscoveryService(
            bus=bus,
            adapter_id=args.adapter_id,
            scan_mode=args.scan_mode,
            restart_delay=args.restart_delay,
            publish_interval=args.publish_interval,
            publish_all=args.publish_all,
        )
        try:
            service_task = asyncio.create_task(service.run())
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            done, pending = await asyncio.wait(
                {service_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            service.stop()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        finally:
            bus.close()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
