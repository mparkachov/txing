from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

try:
    import watchtower
except ImportError:
    watchtower = None

from .shadow_store import (
    DEFAULT_BATTERY_PERCENT,
    DEFAULT_SHADOW_FILE,
    get_reported_battery_percent,
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
DEFAULT_LOCK_FILE = Path("/tmp/txing_gw.lock")
DEFAULT_THING_NAME = "txing"
DEFAULT_AWS_CONNECT_TIMEOUT = 20.0
DEFAULT_CLOUDWATCH_LOG_GROUP = "/txing/gw"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CERT_DIR = REPO_ROOT / "certs"
DEFAULT_IOT_ENDPOINT_FILE = DEFAULT_CERT_DIR / "iot-data-ats.endpoint"
DEFAULT_CERT_FILE = DEFAULT_CERT_DIR / "txing-gw.cert.pem"
DEFAULT_KEY_FILE = DEFAULT_CERT_DIR / "txing-gw.private.key"
DEFAULT_CA_FILE = DEFAULT_CERT_DIR / "AmazonRootCA1.pem"

LOGGER = logging.getLogger("gw.ble_bridge")
MQTT_LOGGER = logging.getLogger("gw.ble_bridge.mqtt")


class ImportantOrWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or bool(
            getattr(record, "important", False)
        )


def _log_important(
    logger: logging.Logger,
    message: str,
    *args: Any,
    level: int = logging.INFO,
) -> None:
    logger.log(level, message, *args, extra={"important": True})


def _default_cloudwatch_log_stream(thing_name: str) -> str:
    hostname = socket.gethostname().split(".", 1)[0] or "gw"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{thing_name}-{hostname}-{timestamp}-{os.getpid()}"


def _extract_desired_power_from_shadow(payload: dict[str, Any]) -> bool | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    desired = state.get("desired")
    if not isinstance(desired, dict):
        return None
    mcu = desired.get("mcu")
    if not isinstance(mcu, dict):
        return None
    value = mcu.get("power")
    return value if isinstance(value, bool) else None


def _extract_desired_power_from_delta(payload: dict[str, Any]) -> bool | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    mcu = state.get("mcu")
    if not isinstance(mcu, dict):
        return None
    value = mcu.get("power")
    return value if isinstance(value, bool) else None


def _extract_reported_power(payload: dict[str, Any]) -> bool | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    reported = state.get("reported")
    if not isinstance(reported, dict):
        return None
    mcu = reported.get("mcu")
    if not isinstance(mcu, dict):
        return None
    value = mcu.get("power")
    return value if isinstance(value, bool) else None


def _extract_reported_battery_percent(payload: dict[str, Any]) -> int | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    reported = state.get("reported")
    if not isinstance(reported, dict):
        return None
    mcu = reported.get("mcu")
    if not isinstance(mcu, dict):
        return None
    value = mcu.get("batteryPercent")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    return None


def _read_iot_endpoint(explicit_endpoint: str | None, endpoint_file: Path) -> str:
    if explicit_endpoint:
        endpoint = explicit_endpoint.strip()
        if endpoint:
            return endpoint

    try:
        endpoint = endpoint_file.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise RuntimeError(
            f"failed to read AWS IoT endpoint file {endpoint_file}: {err}"
        ) from err
    if not endpoint:
        raise RuntimeError(f"AWS IoT endpoint file {endpoint_file} is empty")
    return endpoint


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{description} not found: {path}")


@dataclass(slots=True)
class BridgeConfig:
    name_fragment: str = DEFAULT_NAME_FRAGMENT
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    shadow_file: Path = DEFAULT_SHADOW_FILE
    lock_file: Path = DEFAULT_LOCK_FILE
    thing_name: str = DEFAULT_THING_NAME
    iot_endpoint: str = ""
    cert_file: Path = DEFAULT_CERT_FILE
    key_file: Path = DEFAULT_KEY_FILE
    ca_file: Path = DEFAULT_CA_FILE
    client_id: str = ""
    aws_connect_timeout: float = DEFAULT_AWS_CONNECT_TIMEOUT


@dataclass(slots=True)
class ShadowState:
    desired_power: bool | None = None
    reported_power: bool = False
    battery_percent: int = DEFAULT_BATTERY_PERCENT
    snapshot_file: Path = DEFAULT_SHADOW_FILE

    def set_desired(self, power: bool | None) -> None:
        self.desired_power = power

    def set_reported(self, power: bool, battery_percent: int | None = None) -> None:
        self.reported_power = power
        if battery_percent is not None:
            self.battery_percent = battery_percent

    def payload(self) -> dict[str, dict[str, dict[str, dict[str, bool | int]]]]:
        state: dict[str, dict[str, dict[str, bool | int]]] = {
            "reported": {
                "mcu": {
                    "power": self.reported_power,
                    "batteryPercent": self.battery_percent,
                }
            },
        }
        if self.desired_power is not None:
            state["desired"] = {"mcu": {"power": self.desired_power}}
        return {"state": state}

    def clear_desired_if_synced(self) -> bool:
        if self.desired_power is not None and self.desired_power == self.reported_power:
            self.desired_power = None
            return True
        return False

    def log_state(self, context: str) -> None:
        save_shadow(self.payload(), self.snapshot_file)
        LOGGER.info("%s shadow=%s", context, json.dumps(self.payload(), sort_keys=True))


@dataclass(slots=True)
class AwsShadowUpdate:
    source: str
    has_desired: bool = False
    desired_power: bool | None = None
    reported_power: bool | None = None
    battery_percent: int | None = None


class AwsShadowClient:
    def __init__(self, config: BridgeConfig) -> None:
        self._config = config
        self._topic_prefix = f"$aws/things/{config.thing_name}/shadow"
        self._topic_get = f"{self._topic_prefix}/get"
        self._topic_get_accepted = f"{self._topic_prefix}/get/accepted"
        self._topic_get_rejected = f"{self._topic_prefix}/get/rejected"
        self._topic_update = f"{self._topic_prefix}/update"
        self._topic_update_delta = f"{self._topic_prefix}/update/delta"

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self._client.enable_logger(MQTT_LOGGER)
        self._client.tls_set(
            ca_certs=str(config.ca_file),
            certfile=str(config.cert_file),
            keyfile=str(config.key_file),
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event: asyncio.Event | None = None
        self._updates: asyncio.Queue[AwsShadowUpdate] | None = None
        self._initial_snapshot_future: asyncio.Future[dict[str, Any]] | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._connected_event and self._connected_event.is_set())

    async def connect_and_get_initial_snapshot(
        self, timeout_seconds: float
    ) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        self._connected_event = asyncio.Event()
        self._updates = asyncio.Queue()
        self._initial_snapshot_future = self._loop.create_future()

        connect_rc = self._client.connect(
            host=self._config.iot_endpoint,
            port=8883,
            keepalive=60,
        )
        if connect_rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"failed to initiate AWS IoT MQTT connection (rc={connect_rc})"
            )
        self._client.loop_start()

        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout_seconds)
            deadline = self._loop.time() + timeout_seconds
            while True:
                await self._request_shadow_get()
                remaining = deadline - self._loop.time()
                if remaining <= 0:
                    raise TimeoutError(
                        "timed out waiting for initial AWS IoT shadow snapshot"
                    )
                try:
                    snapshot = await asyncio.wait_for(
                        asyncio.shield(self._initial_snapshot_future),
                        timeout=min(2.0, remaining),
                    )
                    return snapshot
                except TimeoutError:
                    continue
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def drain_updates(self) -> list[AwsShadowUpdate]:
        if self._updates is None:
            return []
        updates: list[AwsShadowUpdate] = []
        while True:
            try:
                updates.append(self._updates.get_nowait())
            except asyncio.QueueEmpty:
                break
        return updates

    async def wait_for_updates(
        self,
        timeout_seconds: float | None = None,
    ) -> list[AwsShadowUpdate]:
        if self._updates is None:
            return []

        try:
            if timeout_seconds is None:
                first = await self._updates.get()
            else:
                first = await asyncio.wait_for(
                    self._updates.get(),
                    timeout=timeout_seconds,
                )
        except TimeoutError:
            return []

        updates = [first]
        while True:
            try:
                updates.append(self._updates.get_nowait())
            except asyncio.QueueEmpty:
                break
        return updates

    async def set_reported_state(
        self,
        *,
        power: bool,
        battery_percent: int,
        clear_desired_power: bool,
    ) -> None:
        state: dict[str, Any] = {
            "reported": {
                "mcu": {
                    "power": power,
                    "batteryPercent": battery_percent,
                }
            }
        }
        if clear_desired_power:
            state["desired"] = {"mcu": {"power": None}}

        await self._publish_json(
            self._topic_update,
            {"state": state},
        )

    async def _publish_json(self, topic: str, payload: dict[str, Any]) -> None:
        payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)

        def _publish_sync() -> None:
            info = self._client.publish(topic, payload=payload_text, qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"failed to publish to {topic}: rc={info.rc} payload={payload_text}"
                )
            info.wait_for_publish(timeout=10)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"publish to {topic} did not complete successfully: rc={info.rc}"
                )

        await asyncio.to_thread(_publish_sync)

    async def _request_shadow_get(self) -> None:
        def _publish_sync() -> None:
            info = self._client.publish(self._topic_get, payload="{}", qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"failed to publish shadow get to {self._topic_get} (rc={info.rc})"
                )
            info.wait_for_publish(timeout=10)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(
                    f"shadow get publish did not complete successfully: rc={info.rc}"
                )

        await asyncio.to_thread(_publish_sync)

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        is_failure = bool(getattr(reason_code, "is_failure", False))
        if not hasattr(reason_code, "is_failure"):
            is_failure = reason_code != 0

        if is_failure:
            error = RuntimeError(f"AWS IoT MQTT CONNACK rejected (reason={reason_code})")
            LOGGER.error("%s", error)
            self._set_initial_snapshot_exception(error)
            return

        _log_important(
            LOGGER,
            "Connected to AWS IoT endpoint=%s thing=%s client_id=%s",
            self._config.iot_endpoint,
            self._config.thing_name,
            self._config.client_id,
        )

        for topic in (self._topic_get_accepted, self._topic_get_rejected, self._topic_update_delta):
            subscribe_rc, _mid = client.subscribe(topic, qos=1)
            if subscribe_rc != mqtt.MQTT_ERR_SUCCESS:
                error = RuntimeError(
                    f"failed to subscribe to {topic} (rc={subscribe_rc})"
                )
                LOGGER.error("%s", error)
                self._set_initial_snapshot_exception(error)
                return

        if self._loop and self._connected_event:
            self._loop.call_soon_threadsafe(self._connected_event.set)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        is_failure = bool(getattr(reason_code, "is_failure", False))
        if not hasattr(reason_code, "is_failure"):
            is_failure = reason_code != 0

        if is_failure:
            LOGGER.warning(
                "AWS IoT MQTT disconnected unexpectedly (reason=%s)",
                reason_code,
            )
        else:
            _log_important(LOGGER, "Disconnected from AWS IoT MQTT")
        if self._loop and self._connected_event:
            self._loop.call_soon_threadsafe(self._connected_event.clear)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        try:
            payload: dict[str, Any] = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring non-JSON payload on topic %s", msg.topic)
            return

        if msg.topic == self._topic_get_rejected:
            error = RuntimeError(f"shadow get rejected: {payload}")
            LOGGER.error("%s", error)
            self._set_initial_snapshot_exception(error)
            return

        if msg.topic == self._topic_get_accepted:
            update = AwsShadowUpdate(
                source="shadow/get/accepted",
                has_desired=True,
                desired_power=_extract_desired_power_from_shadow(payload),
                reported_power=_extract_reported_power(payload),
                battery_percent=_extract_reported_battery_percent(payload),
            )
            self._enqueue_update(update)
            self._set_initial_snapshot(payload)
            return

        if msg.topic == self._topic_update_delta:
            desired_power = _extract_desired_power_from_delta(payload)
            if desired_power is None:
                LOGGER.debug("Ignored shadow delta without desired.mcu.power: %s", payload)
                return
            update = AwsShadowUpdate(
                source="shadow/update/delta",
                has_desired=True,
                desired_power=desired_power,
            )
            self._enqueue_update(update)

    def _enqueue_update(self, update: AwsShadowUpdate) -> None:
        if self._loop is None or self._updates is None:
            return
        self._loop.call_soon_threadsafe(self._updates.put_nowait, update)

    def _set_initial_snapshot(self, payload: dict[str, Any]) -> None:
        if self._loop is None or self._initial_snapshot_future is None:
            return

        def _set() -> None:
            if not self._initial_snapshot_future.done():
                self._initial_snapshot_future.set_result(payload)

        self._loop.call_soon_threadsafe(_set)

    def _set_initial_snapshot_exception(self, error: Exception) -> None:
        if self._loop is None or self._initial_snapshot_future is None:
            return

        def _set() -> None:
            if not self._initial_snapshot_future.done():
                self._initial_snapshot_future.set_exception(error)

        self._loop.call_soon_threadsafe(_set)


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


class BleSleepBridge:
    def __init__(
        self,
        config: BridgeConfig,
        shadow: ShadowState,
        cloud_shadow: AwsShadowClient,
    ) -> None:
        self._config = config
        self._shadow = shadow
        self._cloud_shadow = cloud_shadow
        self._cached_device_id: str | None = None
        self._client: BleakClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._disconnect_event: asyncio.Event | None = None

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._disconnect_event = asyncio.Event()
        _log_important(
            LOGGER,
            "Running in BLE mode; waiting for cloud shadow updates via MQTT",
        )
        pending_updates = self._cloud_shadow.drain_updates()
        try:
            while True:
                if pending_updates:
                    await self._apply_cloud_shadow_updates(updates=pending_updates)
                    pending_updates = []

                if not self._is_connected():
                    try:
                        await self._ensure_connected()
                    except Exception:
                        LOGGER.exception(
                            "BLE unavailable; will retry in %.1fs",
                            self._config.reconnect_delay,
                        )
                        pending_updates = await self._wait_for_updates_or_disconnect(
                            timeout_seconds=self._config.reconnect_delay
                        )
                        continue

                await self._process_desired_power_once()

                retry_timeout: float | None = None
                if (
                    self._shadow.desired_power is not None
                    and self._shadow.desired_power != self._shadow.reported_power
                ):
                    retry_timeout = self._config.reconnect_delay

                pending_updates = await self._wait_for_updates_or_disconnect(
                    timeout_seconds=retry_timeout
                )
        finally:
            await self._safe_disconnect()

    async def run_no_ble(self) -> None:
        _log_important(
            LOGGER,
            "Running in --no-ble mode; waiting for cloud shadow updates via MQTT",
        )
        await self._process_desired_no_ble_once()
        while True:
            retry_timeout: float | None = None
            if (
                self._shadow.desired_power is not None
                and self._shadow.desired_power != self._shadow.reported_power
            ):
                retry_timeout = self._config.reconnect_delay

            updates = await self._cloud_shadow.wait_for_updates(
                timeout_seconds=retry_timeout
            )
            await self._apply_cloud_shadow_updates(updates=updates)
            await self._process_desired_no_ble_once()

    async def _apply_cloud_shadow_updates(
        self,
        updates: list[AwsShadowUpdate] | None = None,
    ) -> None:
        if updates is None:
            updates = self._cloud_shadow.drain_updates()
        for update in updates:
            changed = False
            if update.has_desired and self._shadow.desired_power != update.desired_power:
                self._shadow.set_desired(update.desired_power)
                changed = True
            if (
                update.reported_power is not None
                and self._shadow.reported_power != update.reported_power
            ):
                self._shadow.set_reported(update.reported_power)
                changed = True
            if (
                update.battery_percent is not None
                and self._shadow.battery_percent != update.battery_percent
            ):
                self._shadow.set_reported(
                    self._shadow.reported_power,
                    battery_percent=update.battery_percent,
                )
                changed = True

            if changed:
                self._shadow.log_state(f"Applied cloud shadow update ({update.source})")

    async def _ensure_connected(self) -> None:
        if self._is_connected():
            return

        await self._safe_disconnect()
        device = await self._discover_target()

        client = BleakClient(device, disconnected_callback=self._handle_disconnect)
        self._client = client
        try:
            connected = await client.connect()
            if connected is False:
                raise RuntimeError("BLE connect returned False")
            await client.get_services()
            self._cached_device_id = device.address
            _log_important(
                LOGGER,
                "Connected to %s (%s)",
                device.address,
                device.name or "<unnamed>",
            )
            await self._sync_reported_from_device_on_connect()
        except Exception:
            self._client = None
            raise

    async def _process_desired_no_ble_once(self) -> None:
        target_power = self._shadow.desired_power
        if target_power is None:
            return

        if self._shadow.reported_power == target_power:
            await self._clear_desired_if_synced(
                context="No-op in --no-ble mode: desired already equals reported",
            )
            return

        LOGGER.info(
            "Dry-run: would send Sleep Command sleep=%s; updating reported in cloud",
            not target_power,
        )
        self._shadow.set_reported(target_power)
        await self._publish_reported_update(
            clear_desired_power=True,
            context="Reported updated after dry-run command success",
        )

    async def _process_desired_power_once(self) -> None:
        target_power = self._shadow.desired_power
        if target_power is None:
            return

        if self._shadow.reported_power == target_power:
            await self._clear_desired_if_synced(
                context="No-op: desired already equals reported",
            )
            return

        if not self._is_connected():
            LOGGER.info(
                "Desired command pending (desired=%s): BLE disconnected, waiting for reconnect",
                target_power,
            )
            return

        try:
            await self._send_sleep_command(sleep=not target_power)
        except Exception:
            LOGGER.exception(
                "Failed to send BLE command for desired power=%s; will retry",
                target_power,
            )
            await self._safe_disconnect()
            return

        self._shadow.set_reported(target_power)
        await self._publish_reported_update(
            clear_desired_power=True,
            context="Reported updated after BLE command success",
        )

    async def _clear_desired_if_synced(self, context: str) -> None:
        if self._shadow.desired_power is None:
            return
        await self._publish_reported_update(
            clear_desired_power=True,
            context=context,
        )

    async def _publish_reported_update(
        self,
        *,
        clear_desired_power: bool,
        context: str,
    ) -> None:
        try:
            await self._cloud_shadow.set_reported_state(
                power=self._shadow.reported_power,
                battery_percent=self._shadow.battery_percent,
                clear_desired_power=clear_desired_power,
            )
        except Exception:
            LOGGER.exception("Failed to publish reported shadow update; will retry")
            return

        if clear_desired_power:
            self._shadow.clear_desired_if_synced()
        self._shadow.log_state(context)

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
        reported_power = sleep_flag == 0x00

        self._shadow.set_reported(
            power=reported_power,
            battery_percent=battery_pct,
        )
        await self._publish_reported_update(
            clear_desired_power=self._shadow.desired_power == reported_power,
            context="Reported synchronized from MCU state report on connect",
        )
        LOGGER.info(
            "MCU state report on connect: battery_pct=%s sleep=%s => power=%s",
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
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            LOGGER.exception("Failed to disconnect BLE client cleanly")

    def _handle_disconnect(self, _: BleakClient) -> None:
        LOGGER.warning("BLE connection lost")
        if self._loop is not None and self._disconnect_event is not None:
            self._loop.call_soon_threadsafe(self._disconnect_event.set)

    async def _wait_for_updates_or_disconnect(
        self,
        timeout_seconds: float | None = None,
    ) -> list[AwsShadowUpdate]:
        updates_task = asyncio.create_task(self._cloud_shadow.wait_for_updates())
        disconnect_task = asyncio.create_task(self._wait_for_disconnect_event())
        try:
            done, _pending = await asyncio.wait(
                {updates_task, disconnect_task},
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                return []
            if updates_task in done:
                return updates_task.result()
            return []
        finally:
            for task in (updates_task, disconnect_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(updates_task, disconnect_task, return_exceptions=True)

    async def _wait_for_disconnect_event(self) -> None:
        if self._disconnect_event is None:
            return
        await self._disconnect_event.wait()
        self._disconnect_event.clear()

    def _is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gw",
        description="Txing gateway process (AWS IoT Shadow + BLE bridge)",
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
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before retrying failed loops (default: 1)",
    )
    parser.add_argument(
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Path to local shadow mirror file (default: /tmp/txing_shadow.json)",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=DEFAULT_LOCK_FILE,
        help="Path to single-instance lock file (default: /tmp/txing_gw.lock)",
    )
    parser.add_argument(
        "--thing-name",
        default=DEFAULT_THING_NAME,
        help="AWS IoT thing name (default: txing)",
    )
    parser.add_argument(
        "--iot-endpoint",
        default=None,
        help="AWS IoT data endpoint hostname; if omitted, --iot-endpoint-file is used",
    )
    parser.add_argument(
        "--iot-endpoint-file",
        type=Path,
        default=DEFAULT_IOT_ENDPOINT_FILE,
        help=f"File containing AWS IoT endpoint (default: {DEFAULT_IOT_ENDPOINT_FILE})",
    )
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=DEFAULT_CERT_FILE,
        help=f"Client certificate PEM file (default: {DEFAULT_CERT_FILE})",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=DEFAULT_KEY_FILE,
        help=f"Client private key file (default: {DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=DEFAULT_CA_FILE,
        help=f"Root CA file (default: {DEFAULT_CA_FILE})",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="MQTT client id (default: txing-gw-<pid>)",
    )
    parser.add_argument(
        "--aws-connect-timeout",
        type=float,
        default=DEFAULT_AWS_CONNECT_TIMEOUT,
        help="Seconds to wait for initial AWS MQTT connect + shadow get (default: 20)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Minimum severity uploaded to CloudWatch Logs (default: INFO)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose stdout logging (useful for interactive debugging)",
    )
    parser.add_argument(
        "--cloudwatch-log-group",
        default=DEFAULT_CLOUDWATCH_LOG_GROUP,
        help="CloudWatch Logs group name for gateway logs (default: /txing/gw)",
    )
    parser.add_argument(
        "--cloudwatch-log-stream",
        default=None,
        help="CloudWatch Logs stream name (default: generated per host/process)",
    )
    parser.add_argument(
        "--no-cloudwatch-logs",
        action="store_true",
        help="Disable direct CloudWatch Logs publishing",
    )
    parser.add_argument(
        "--no-ble",
        action="store_true",
        help="Do not use BLE; still sync desired/reported with AWS shadow",
    )
    return parser.parse_args()


def _build_shadow_from_snapshot(
    snapshot: dict[str, Any],
    *,
    snapshot_file: Path,
) -> ShadowState:
    cached = load_shadow(snapshot_file)
    reported_power = _extract_reported_power(snapshot)
    battery_percent = _extract_reported_battery_percent(snapshot)
    return ShadowState(
        desired_power=_extract_desired_power_from_shadow(snapshot),
        reported_power=(
            reported_power if reported_power is not None else get_reported_power(cached)
        ),
        battery_percent=(
            battery_percent
            if battery_percent is not None
            else get_reported_battery_percent(cached)
        ),
        snapshot_file=snapshot_file,
    )


def _configure_logging(args: argparse.Namespace) -> None:
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(logging.DEBUG if args.debug else logging.INFO)
    if not args.debug:
        stdout_handler.addFilter(ImportantOrWarningFilter())
    root_logger.addHandler(stdout_handler)

    if args.no_cloudwatch_logs:
        _log_important(LOGGER, "CloudWatch log streaming disabled (--no-cloudwatch-logs)")
        return

    if watchtower is None:
        print(
            "gw start warning: watchtower dependency is not installed; "
            "CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    stream_name = args.cloudwatch_log_stream or _default_cloudwatch_log_stream(
        args.thing_name
    )
    try:
        cloudwatch_handler = watchtower.CloudWatchLogHandler(
            log_group_name=args.cloudwatch_log_group,
            log_stream_name=stream_name,
            create_log_group=False,
            create_log_stream=True,
            send_interval=5,
        )
    except Exception as err:
        print(
            f"gw start warning: failed to initialize CloudWatch log handler: {err}",
            file=sys.stderr,
        )
        return

    cloudwatch_handler.setLevel(getattr(logging, args.log_level))
    cloudwatch_handler.setFormatter(formatter)
    root_logger.addHandler(cloudwatch_handler)
    _log_important(
        LOGGER,
        "CloudWatch log streaming enabled group=%s stream=%s",
        args.cloudwatch_log_group,
        stream_name,
    )


def main() -> None:
    args = _parse_args()
    _configure_logging(args)

    try:
        iot_endpoint = _read_iot_endpoint(args.iot_endpoint, args.iot_endpoint_file)
        _require_file(args.cert_file, "AWS IoT client certificate")
        _require_file(args.key_file, "AWS IoT client private key")
        _require_file(args.ca_file, "AWS IoT root CA")
    except RuntimeError as err:
        print(f"gw start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    config = BridgeConfig(
        name_fragment=args.name,
        scan_timeout=args.scan_timeout,
        reconnect_delay=args.reconnect_delay,
        shadow_file=args.shadow_file,
        lock_file=args.lock_file,
        thing_name=args.thing_name,
        iot_endpoint=iot_endpoint,
        cert_file=args.cert_file,
        key_file=args.key_file,
        ca_file=args.ca_file,
        client_id=args.client_id or f"txing-gw-{os.getpid()}",
        aws_connect_timeout=args.aws_connect_timeout,
    )

    lock = InstanceLock(config.lock_file)
    try:
        lock.acquire()
    except RuntimeError as err:
        print(f"gw start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    _log_important(
        LOGGER,
        "Gateway started pid=%s lock=%s thing=%s",
        os.getpid(),
        config.lock_file,
        config.thing_name,
    )
    LOGGER.info(
        "AWS IoT config endpoint=%s thing=%s cert=%s key=%s ca=%s client_id=%s",
        config.iot_endpoint,
        config.thing_name,
        config.cert_file,
        config.key_file,
        config.ca_file,
        config.client_id,
    )

    async def _runner() -> None:
        cloud_shadow = AwsShadowClient(config)
        snapshot = await cloud_shadow.connect_and_get_initial_snapshot(
            timeout_seconds=config.aws_connect_timeout,
        )
        shadow = _build_shadow_from_snapshot(snapshot, snapshot_file=config.shadow_file)
        shadow.log_state("Initialized from AWS IoT shadow snapshot")

        bridge = BleSleepBridge(config, shadow, cloud_shadow)
        try:
            if args.no_ble:
                while True:
                    try:
                        await bridge.run_no_ble()
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
        finally:
            await cloud_shadow.disconnect()

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        _log_important(LOGGER, "Shutting down gateway")
    finally:
        lock.release()
        logging.shutdown()
