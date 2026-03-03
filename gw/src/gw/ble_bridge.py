from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

TXING_SERVICE_UUID = "5A35B7B9-B4D8-21D6-F1FE-A61B1745ED7C"
SLEEP_COMMAND_UUID = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100"
TXING_MFG_ID = 0xFFFF
TXING_MFG_MAGIC = b"TX"

DEFAULT_NAME_FRAGMENT = "txing"
DEFAULT_SCAN_TIMEOUT = 12.0
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_WAKE_FILE = Path("/tmp/wake")
DEFAULT_SLEEP_FILE = Path("/tmp/sleep")

LOGGER = logging.getLogger("gw.ble_bridge")


@dataclass(slots=True)
class BridgeConfig:
    name_fragment: str = DEFAULT_NAME_FRAGMENT
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    poll_interval: float = DEFAULT_POLL_INTERVAL
    wake_file: Path = DEFAULT_WAKE_FILE
    sleep_file: Path = DEFAULT_SLEEP_FILE


class BleSleepBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self._config = config
        self._cached_device_id: str | None = None
        self._client: BleakClient | None = None
        self._disconnected = asyncio.Event()
        self._disconnected.set()

    async def run(self) -> None:
        try:
            while True:
                await self._ensure_connected()
                await self._poll_trigger_files()
        finally:
            await self._safe_disconnect()

    async def _ensure_connected(self) -> None:
        if self._is_connected():
            return

        await self._safe_disconnect()
        device = await self._discover_target()

        client = BleakClient(device, disconnected_callback=self._handle_disconnect)
        self._disconnected.clear()
        self._client = client
        try:
            connected = await client.connect()
            if connected is False:
                raise RuntimeError("BLE connect returned False")
            await client.get_services()
            self._cached_device_id = device.address
            LOGGER.info("Connected to %s (%s)", device.address, device.name or "<unnamed>")
        except Exception:
            self._client = None
            self._disconnected.set()
            raise

    async def _poll_trigger_files(self) -> None:
        while self._is_connected() and not self._disconnected.is_set():
            pending = self._pending_commands()
            for trigger_file, sleep_value in pending:
                if not trigger_file.exists():
                    continue

                await self._send_sleep_command(sleep=sleep_value)
                trigger_file.unlink(missing_ok=True)
                LOGGER.info(
                    "Processed %s (sleep=%s) and removed trigger file",
                    trigger_file,
                    sleep_value,
                )

            await asyncio.sleep(self._config.poll_interval)

    def _pending_commands(self) -> list[tuple[Path, bool]]:
        candidates: list[tuple[float, Path, bool]] = []
        for path, sleep_value in (
            (self._config.wake_file, False),
            (self._config.sleep_file, True),
        ):
            if not path.exists():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, path, sleep_value))

        candidates.sort(key=lambda item: item[0])
        return [(path, sleep_value) for _, path, sleep_value in candidates]

    async def _send_sleep_command(self, sleep: bool) -> None:
        if not self._is_connected():
            raise RuntimeError("BLE client is not connected")
        assert self._client is not None

        payload = b"\x01" if sleep else b"\x00"
        await self._client.write_gatt_char(
            SLEEP_COMMAND_UUID,
            payload,
            response=True,
        )
        LOGGER.info("Sent Sleep Command sleep=%s", sleep)

    async def _discover_target(self) -> BLEDevice:
        if self._cached_device_id:
            LOGGER.info("Trying cached BLE id in memory: %s", self._cached_device_id)
            cached_device = await BleakScanner.find_device_by_address(
                self._cached_device_id,
                timeout=2.0,
            )
            if cached_device:
                return cached_device
            LOGGER.warning("Cached id was not found, falling back to full discovery")

        name_fragment = self._config.name_fragment.lower()

        def matches(device: BLEDevice, adv: AdvertisementData) -> bool:
            service_match = any(
                service.lower() == TXING_SERVICE_UUID
                for service in (adv.service_uuids or [])
            )
            name = (adv.local_name or device.name or "").lower()
            name_match = bool(name) and name_fragment in name
            mfg_data = adv.manufacturer_data or {}
            mfg = mfg_data.get(TXING_MFG_ID)
            mfg_match = mfg is not None and bytes(mfg).startswith(TXING_MFG_MAGIC)
            return service_match or name_match or mfg_match

        LOGGER.info(
            "Discovering BLE target (service=%s, name~=%s, timeout=%.1fs)",
            TXING_SERVICE_UUID,
            self._config.name_fragment,
            self._config.scan_timeout,
        )
        device = await BleakScanner.find_device_by_filter(
            matches,
            timeout=self._config.scan_timeout,
        )
        if device is None:
            raise RuntimeError(
                "BLE device discovery timeout: no matching device found "
                f"(service={TXING_SERVICE_UUID}, name~={self._config.name_fragment})"
            )
        return device

    async def _safe_disconnect(self) -> None:
        client = self._client
        self._client = None
        self._disconnected.set()
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            LOGGER.exception("Failed to disconnect BLE client cleanly")

    def _handle_disconnect(self, _: BleakClient) -> None:
        LOGGER.warning("BLE connection lost")
        self._disconnected.set()

    def _is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gw",
        description="Txing gateway BLE bridge process",
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_NAME_FRAGMENT,
        help="BLE local name fragment for discovery (default: txing)",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=DEFAULT_SCAN_TIMEOUT,
        help="Seconds to wait during BLE discovery (default: 12)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help="Seconds between /tmp trigger checks (default: 1)",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before reconnect attempts after failure (default: 1)",
    )
    parser.add_argument(
        "--wake-file",
        type=Path,
        default=DEFAULT_WAKE_FILE,
        help="Path to wake trigger file (default: /tmp/wake)",
    )
    parser.add_argument(
        "--sleep-file",
        type=Path,
        default=DEFAULT_SLEEP_FILE,
        help="Path to sleep trigger file (default: /tmp/sleep)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = BridgeConfig(
        name_fragment=args.name,
        scan_timeout=args.scan_timeout,
        reconnect_delay=args.reconnect_delay,
        poll_interval=args.poll_interval,
        wake_file=args.wake_file,
        sleep_file=args.sleep_file,
    )
    bridge = BleSleepBridge(config)

    async def _runner() -> None:
        while True:
            try:
                await bridge.run()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "BLE bridge loop failed; retrying in %.1fs",
                    config.reconnect_delay,
                )
                await asyncio.sleep(config.reconnect_delay)

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        LOGGER.info("Shutting down BLE bridge")
