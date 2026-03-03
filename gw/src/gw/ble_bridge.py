from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .shadow_store import (
    DEFAULT_SHADOW_FILE,
    POWER_OFF,
    POWER_ON,
    get_desired_power,
    get_reported_power,
    load_shadow,
    save_shadow,
)

TXING_SERVICE_UUID = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100"
SLEEP_COMMAND_UUID = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100"
STATE_REPORT_UUID = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100"
TXING_MFG_ID = 0xFFFF
TXING_MFG_MAGIC = b"TX"

DEFAULT_NAME_FRAGMENT = "txing"
DEFAULT_SCAN_TIMEOUT = 12.0
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_WAKE_FILE = Path("/tmp/wake")
DEFAULT_SLEEP_FILE = Path("/tmp/sleep")
DEFAULT_LOCK_FILE = Path("/tmp/txing_gw.lock")

LOGGER = logging.getLogger("gw.ble_bridge")


@dataclass(slots=True)
class BridgeConfig:
    name_fragment: str = DEFAULT_NAME_FRAGMENT
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    poll_interval: float = DEFAULT_POLL_INTERVAL
    wake_file: Path = DEFAULT_WAKE_FILE
    sleep_file: Path = DEFAULT_SLEEP_FILE
    shadow_file: Path = DEFAULT_SHADOW_FILE
    lock_file: Path = DEFAULT_LOCK_FILE


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._pid = os.getpid()
        self._held = False

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
                    lock_file.write(f"{self._pid}\n")
                self._held = True
                return
            except FileExistsError:
                owner_pid = self._read_owner_pid()
                if owner_pid is not None and self._pid_running(owner_pid):
                    raise RuntimeError(
                        f"another gw instance is already running (pid={owner_pid}, lock={self._path})"
                    )
                # stale lock file
                try:
                    self._path.unlink()
                except FileNotFoundError:
                    pass

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            owner_pid = self._read_owner_pid()
            if owner_pid is None or owner_pid == self._pid:
                self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_owner_pid(self) -> int | None:
        try:
            raw = self._path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


@dataclass(slots=True)
class SimulatedShadow:
    desired_power: str | None = None
    reported_power: str = POWER_OFF
    snapshot_file: Path = DEFAULT_SHADOW_FILE

    def set_desired(self, power: str) -> None:
        self.desired_power = power

    def set_reported(self, power: str) -> None:
        self.reported_power = power

    def payload(self) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
        state: dict[str, dict[str, dict[str, str]]] = {
            "reported": {"mcu": {"power": self.reported_power}},
        }
        if self.desired_power is not None:
            state["desired"] = {"mcu": {"power": self.desired_power}}
        return {"state": state}

    def clear_desired_if_synced(self) -> None:
        if self.desired_power is not None and self.desired_power == self.reported_power:
            self.desired_power = None

    def log_state(self, context: str) -> None:
        save_shadow(self.payload(), self.snapshot_file)
        LOGGER.info("%s shadow=%s", context, json.dumps(self.payload(), sort_keys=True))


class BleSleepBridge:
    def __init__(self, config: BridgeConfig, shadow: SimulatedShadow) -> None:
        self._config = config
        self._shadow = shadow
        self._cached_device_id: str | None = None
        self._client: BleakClient | None = None
        self._disconnected = asyncio.Event()
        self._disconnected.set()

    async def run(self) -> None:
        try:
            while True:
                if not self._is_connected():
                    try:
                        await self._ensure_connected()
                    except Exception:
                        LOGGER.exception(
                            "BLE unavailable; will retry in %.1fs",
                            self._config.reconnect_delay,
                        )
                        await asyncio.sleep(self._config.reconnect_delay)

                await self._process_trigger_files_once()
                await asyncio.sleep(self._config.poll_interval)
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
            await self._sync_reported_from_device_on_connect()
        except Exception:
            self._client = None
            self._disconnected.set()
            raise

    async def _process_trigger_files_once(self) -> None:
        pending = pending_commands(
            wake_file=self._config.wake_file,
            sleep_file=self._config.sleep_file,
        )
        for trigger_file, target_power, sleep_value in pending:
            if not trigger_file.exists():
                continue

            LOGGER.info(
                "Trigger detected %s -> desired power=%s (current desired=%s reported=%s)",
                trigger_file,
                target_power,
                self._shadow.desired_power,
                self._shadow.reported_power,
            )

            if self._shadow.desired_power != target_power:
                self._shadow.set_desired(target_power)
                self._shadow.log_state(f"Desired updated from trigger {trigger_file}")

            if self._shadow.reported_power == target_power:
                trigger_file.unlink(missing_ok=True)
                self._shadow.clear_desired_if_synced()
                self._shadow.log_state(
                    f"No-op: desired already equals reported ({trigger_file})"
                )
                LOGGER.info(
                    "No-op for %s: reported power already %s; removed trigger file",
                    trigger_file,
                    target_power,
                )
                continue

            if not self._is_connected():
                LOGGER.info(
                    "Command pending for %s (desired=%s): BLE disconnected, waiting for reconnect",
                    trigger_file,
                    target_power,
                )
                continue

            try:
                await self._send_sleep_command(sleep=sleep_value)
            except Exception:
                LOGGER.exception(
                    "Failed to send command for %s (desired=%s); will retry",
                    trigger_file,
                    target_power,
                )
                await self._safe_disconnect()
                continue

            trigger_file.unlink(missing_ok=True)
            self._shadow.set_reported(target_power)
            self._shadow.clear_desired_if_synced()
            self._shadow.log_state(
                f"Reported updated after BLE command success ({trigger_file})"
            )
            LOGGER.info(
                "Processed %s (power=%s, sleep=%s) and removed trigger file",
                trigger_file,
                target_power,
                sleep_value,
            )

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

    async def _sync_reported_from_device_on_connect(self) -> None:
        if not self._is_connected():
            return
        assert self._client is not None

        report = await self._client.read_gatt_char(STATE_REPORT_UUID)
        if len(report) < 2:
            raise RuntimeError(
                f"unexpected State Report length: {len(report)} (expected >= 2)"
            )

        battery_pct = int(report[0])
        sleep_flag = int(report[1])
        reported_power = POWER_ON if sleep_flag == 0x00 else POWER_OFF

        self._shadow.set_reported(reported_power)
        self._shadow.clear_desired_if_synced()
        self._shadow.log_state(
            "Reported synchronized from MCU state report on connect"
        )
        LOGGER.info(
            "MCU state report on connect: battery_pct=%s sleep=%s => reported power=%s",
            battery_pct,
            sleep_flag == 0x01,
            reported_power,
        )

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
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Path to simulated shadow snapshot file (default: /tmp/txing_shadow.json)",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=DEFAULT_LOCK_FILE,
        help="Path to single-instance lock file (default: /tmp/txing_gw.lock)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--no-ble",
        action="store_true",
        help="Do not use BLE; only poll trigger files and log actions",
    )
    return parser.parse_args()


def pending_commands(
    wake_file: Path, sleep_file: Path
) -> list[tuple[Path, str, bool]]:
    candidates: list[tuple[float, Path, str, bool]] = []
    for path, target_power, sleep_value in (
        (wake_file, POWER_ON, False),
        (sleep_file, POWER_OFF, True),
    ):
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, path, target_power, sleep_value))

    candidates.sort(key=lambda item: item[0])
    return [
        (path, target_power, sleep_value)
        for _, path, target_power, sleep_value in candidates
    ]


async def run_no_ble_loop(config: BridgeConfig, shadow: SimulatedShadow) -> None:
    LOGGER.info(
        "Running in --no-ble mode; polling %s and %s every %.2fs",
        config.wake_file,
        config.sleep_file,
        config.poll_interval,
    )
    while True:
        pending = pending_commands(
            wake_file=config.wake_file,
            sleep_file=config.sleep_file,
        )
        for trigger_file, target_power, sleep_value in pending:
            if not trigger_file.exists():
                continue
            LOGGER.info(
                "Trigger detected %s -> desired power=%s (current desired=%s reported=%s)",
                trigger_file,
                target_power,
                shadow.desired_power,
                shadow.reported_power,
            )
            shadow.set_desired(target_power)
            shadow.log_state(f"Desired updated from trigger {trigger_file}")

            if shadow.reported_power == target_power:
                trigger_file.unlink(missing_ok=True)
                shadow.clear_desired_if_synced()
                shadow.log_state(f"No-op: desired already equals reported ({trigger_file})")
                LOGGER.info(
                    "No-op for %s: reported power already %s; removed trigger file",
                    trigger_file,
                    target_power,
                )
                continue

            LOGGER.info(
                "Dry-run: would send Sleep Command sleep=%s (trigger=%s)",
                sleep_value,
                trigger_file,
            )
            trigger_file.unlink(missing_ok=True)
            shadow.set_reported(target_power)
            shadow.clear_desired_if_synced()
            shadow.log_state(
                f"Reported updated after dry-run command success ({trigger_file})"
            )
            LOGGER.info("Dry-run: removed trigger file %s", trigger_file)

        await asyncio.sleep(config.poll_interval)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = BridgeConfig(
        name_fragment=args.name,
        scan_timeout=args.scan_timeout,
        reconnect_delay=args.reconnect_delay,
        poll_interval=args.poll_interval,
        wake_file=args.wake_file,
        sleep_file=args.sleep_file,
        shadow_file=args.shadow_file,
        lock_file=args.lock_file,
    )

    lock = InstanceLock(config.lock_file)
    try:
        lock.acquire()
    except RuntimeError as err:
        print(f"gw start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    snapshot = load_shadow(config.shadow_file)
    shadow = SimulatedShadow(
        desired_power=get_desired_power(snapshot),
        reported_power=get_reported_power(snapshot),
        snapshot_file=config.shadow_file,
    )
    LOGGER.info("gw instance pid=%s lock=%s", os.getpid(), config.lock_file)
    shadow.log_state("Initialized simulated AWS IoT shadow")
    bridge = BleSleepBridge(config, shadow)

    async def _runner() -> None:
        if args.no_ble:
            while True:
                try:
                    await run_no_ble_loop(config, shadow)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "No-BLE loop failed; retrying in %.1fs",
                        config.reconnect_delay,
                    )
                    await asyncio.sleep(config.reconnect_delay)
            return
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
    finally:
        lock.release()
