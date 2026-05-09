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
    BLE_SCAN_CONTROL_TOPIC,
    BLE_SCAN_PAUSE,
    BLE_SCAN_RESUME,
    BleAdvertisement,
    BleScanControl,
    build_ble_advertisement_topic,
)
from rig.capability_protocol import (
    INVENTORY_TOPIC,
    CapabilityInventory,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

LOGGER = logging.getLogger("rig.ble_discovery")

DEFAULT_ADAPTER_ID = "shared-ble-scanner"
DEFAULT_SCAN_MODE = "active"
DEFAULT_RESTART_DELAY = 2.0
DEFAULT_PUBLISH_INTERVAL = 2.0
DEFAULT_UNMATCHED_LOG_INTERVAL = 15.0


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
        self._logged_publish_keys: set[str] = set()
        self._last_unmatched_log_at = 0.0
        self._unmatched_count = 0
        self._unmatched_names: set[str] = set()
        self._seq = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scanner: Any | None = None
        self._scan_control_event = asyncio.Event()
        self._scan_pause_deadlines_by_adapter_id: dict[str, int] = {}

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        inventory_subscription = await self._bus.subscribe(
            INVENTORY_TOPIC,
            self._handle_inventory,
        )
        scan_control_subscription = await self._bus.subscribe(
            BLE_SCAN_CONTROL_TOPIC,
            self._handle_scan_control,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    self._expire_scan_pauses()
                    if self._is_scan_paused():
                        await self._stop_active_scanner()
                        await self._wait_for_stop_or_scan_control(self._scan_pause_wait_seconds())
                        continue
                    await self._start_active_scanner()
                    await self._wait_for_stop_or_scan_control(1.0)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await self._stop_active_scanner()
                    LOGGER.exception(
                        "Shared BLE discovery scanner failed; retrying in %.1f seconds",
                        self._restart_delay,
                    )
                    await _sleep_until_stop(self._stop_event, self._restart_delay)
        finally:
            await self._stop_active_scanner()
            _close_resource(scan_control_subscription)
            _close_resource(inventory_subscription)
            await self._drain_publish_tasks()

    async def _handle_inventory(self, _topic: str, payload: bytes) -> None:
        try:
            inventory = CapabilityInventory.from_payload(payload)
        except Exception as err:
            LOGGER.warning("Invalid BLE discovery inventory ignored: %s", err)
            return

        target_addresses: set[str] = set()
        target_names: set[str] = set()
        for device in inventory.devices:
            if "ble" not in device.capabilities:
                continue
            target_names.add(device.thing_name)

        previous_targets = (self._target_addresses, self._target_names)
        self._targets_by_adapter_id[inventory.manager_id] = (
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
            self._logged_publish_keys = {
                key
                for key in self._logged_publish_keys
                if key in self._target_addresses or key in self._target_names
            }
            LOGGER.info(
                "Updated shared BLE discovery targets adapters=%s addresses=%d names=%s",
                ",".join(sorted(self._targets_by_adapter_id)),
                len(self._target_addresses),
                ",".join(sorted(self._target_names)) or "-",
            )

    async def _handle_scan_control(self, _topic: str, payload: bytes) -> None:
        try:
            control = BleScanControl.from_payload(payload)
        except Exception as err:
            LOGGER.warning("Invalid BLE scan control ignored: %s", err)
            return

        if control.action == BLE_SCAN_PAUSE:
            deadline_ms = control.deadline_ms or utc_timestamp_ms() + 10_000
            previous_deadline_ms = self._scan_pause_deadlines_by_adapter_id.get(
                control.adapter_id,
                0,
            )
            self._scan_pause_deadlines_by_adapter_id[control.adapter_id] = max(
                previous_deadline_ms,
                deadline_ms,
            )
            LOGGER.info(
                "Paused shared BLE discovery scanner requestedBy=%s reason=%s deadlineMs=%s",
                control.adapter_id,
                control.reason,
                self._scan_pause_deadlines_by_adapter_id[control.adapter_id],
            )
        elif control.action == BLE_SCAN_RESUME:
            self._scan_pause_deadlines_by_adapter_id.pop(control.adapter_id, None)
            LOGGER.info(
                "Resumed shared BLE discovery scanner requestedBy=%s reason=%s",
                control.adapter_id,
                control.reason,
            )
        self._scan_control_event.set()

    async def _start_active_scanner(self) -> None:
        if self._scanner is not None:
            return
        scanner = self._scanner_factory(
            detection_callback=self._handle_detection,
            scanning_mode=self._scan_mode,
            bluez={"filters": {"DuplicateData": True}},
        )
        await _maybe_await(scanner.start())
        self._scanner = scanner
        LOGGER.info("Started shared BLE discovery scanner mode=%s", self._scan_mode)

    async def _stop_active_scanner(self) -> None:
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            await _stop_scanner(scanner)

    async def _wait_for_stop_or_scan_control(self, timeout: float) -> None:
        stop_task = asyncio.create_task(self._stop_event.wait())
        control_task = asyncio.create_task(self._scan_control_event.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_task, control_task},
                timeout=max(timeout, 0.0),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
            if control_task in done:
                self._scan_control_event.clear()
        finally:
            for task in (stop_task, control_task):
                if not task.done():
                    task.cancel()

    def _expire_scan_pauses(self) -> None:
        now_ms = utc_timestamp_ms()
        expired_adapter_ids = [
            adapter_id
            for adapter_id, deadline_ms in self._scan_pause_deadlines_by_adapter_id.items()
            if deadline_ms <= now_ms
        ]
        for adapter_id in expired_adapter_ids:
            self._scan_pause_deadlines_by_adapter_id.pop(adapter_id, None)
        if expired_adapter_ids:
            LOGGER.info(
                "Expired shared BLE discovery scanner pause requests adapters=%s",
                ",".join(sorted(expired_adapter_ids)),
            )

    def _is_scan_paused(self) -> bool:
        return bool(self._scan_pause_deadlines_by_adapter_id)

    def _scan_pause_wait_seconds(self) -> float:
        if not self._scan_pause_deadlines_by_adapter_id:
            return 1.0
        now_ms = utc_timestamp_ms()
        next_deadline_ms = min(self._scan_pause_deadlines_by_adapter_id.values())
        return min(max((next_deadline_ms - now_ms) / 1000.0, 0.05), 1.0)

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
            self._record_unmatched_advertisement(advertisement)
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
        if publish_key is not None and publish_key not in self._logged_publish_keys:
            self._logged_publish_keys.add(publish_key)
            LOGGER.info(
                "Matched shared BLE advertisement key=%s address=%s name=%s rssi=%s",
                publish_key,
                advertisement.address,
                advertisement.name or "-",
                advertisement.rssi,
            )
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

    def _record_unmatched_advertisement(self, advertisement: BleAdvertisement) -> None:
        if not self._target_addresses and not self._target_names:
            return
        self._unmatched_count += 1
        if advertisement.name:
            self._unmatched_names.add(advertisement.name)
        now = asyncio.get_running_loop().time()
        if (now - self._last_unmatched_log_at) < DEFAULT_UNMATCHED_LOG_INTERVAL:
            return
        self._last_unmatched_log_at = now
        sample_names = ",".join(sorted(self._unmatched_names)[:5]) or "-"
        LOGGER.info(
            "Shared BLE scanner has no target match yet targets=%s addressTargets=%d unmatched=%d sampleNames=%s",
            ",".join(sorted(self._target_names)) or "-",
            len(self._target_addresses),
            self._unmatched_count,
            sample_names,
        )
        self._unmatched_count = 0
        self._unmatched_names.clear()

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
