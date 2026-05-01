from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine, Iterable, Mapping
from uuid import UUID

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDBusError, BleakError

try:
    import watchtower
except ImportError:
    watchtower = None

try:
    import boto3
    from botocore.exceptions import ClientError as BotoClientError
except ImportError:
    boto3 = None
    BotoClientError = Exception

from .shadow_store import (
    DEFAULT_BATTERY_MV,
    DEFAULT_BOARD_POWER,
    DEFAULT_BOARD_WIFI_ONLINE,
    DEFAULT_REDCON,
    DEFAULT_REPORTED_ONLINE,
    DEFAULT_REPORTED_POWER,
    DEFAULT_SHADOW_FILE,
)
from .thing_registry import AwsThingRegistryClient, DeviceRegistration, ThingGroupNotFoundError
from aws.auth import (
    build_aws_runtime,
    resolve_aws_region,
    AwsRuntime,
    ensure_aws_profile,
)
from aws.device_registry import AwsDeviceRegistry
from aws.log_groups import DEFAULT_LOG_RETENTION_DAYS, build_rig_log_group_name
from aws.mcp_topics import (
    MCP_DEFAULT_LEASE_TTL_MS,
    MCP_PROTOCOL_VERSION,
    MCP_TRANSPORT,
    build_mcp_descriptor_topic,
    build_mcp_status_payload,
    build_mcp_status_topic,
    parse_mcp_descriptor_or_status_topic,
)
from aws.video_topics import (
    VIDEO_DEFAULT_CODEC,
    VIDEO_SERVICE_NAME,
    VIDEO_STATUS_READY,
    VIDEO_STATUS_UNAVAILABLE,
    VIDEO_TRANSPORT,
    build_video_descriptor_topic,
    build_video_status_topic,
    build_video_topic_root,
    build_video_topics,
    parse_video_descriptor_or_status_topic,
)
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from .sparkplug import (
    DataType,
    Metric,
    build_device_death_payload,
    build_device_report_payload,
    build_device_topic,
    build_node_birth_payload,
    build_node_death_payload,
    build_node_topic,
    decode_redcon_command,
    utc_timestamp_ms,
)

TXING_SERVICE_UUID = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100"
SLEEP_COMMAND_UUID = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100"
STATE_REPORT_UUID = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100"
TXING_MFG_ID = 0xFFFF
TXING_MFG_MAGIC = b"TX"

DEFAULT_NAME_FRAGMENT = "txing"
DEFAULT_SCAN_TIMEOUT = 12.0
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_COMMAND_ACK_TIMEOUT = 2.0
DEFAULT_COMMAND_ACK_POLL_INTERVAL = 0.1
DEFAULT_DEVICE_STALE_AFTER = 0.75
DEFAULT_BLE_ONLINE_STALE_AFTER = 30.0
DEFAULT_BLE_ONLINE_RECOVER_AFTER = 4.0
DEFAULT_BLE_ONLINE_RECOVERY_GAP = 12.0
DEFAULT_ADVERTISEMENT_LOG_INTERVAL = 5.0
DEFAULT_SCAN_MODE = "active"
DEFAULT_LOCK_FILE = Path("/tmp/rig.lock")
DEFAULT_THING_NAME = "txing"
DEFAULT_RIG_NAME = "rig"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_SPARKPLUG_EDGE_NODE_ID = "rig"
DEFAULT_AWS_CONNECT_TIMEOUT = 20.0
DEFAULT_CLOUDWATCH_LOG_GROUP = ""
DEFAULT_MQTT_PUBLISH_TIMEOUT = 10.0
DEFAULT_BOARD_OFFLINE_TIMEOUT = 45.0
DEFAULT_VIDEO_STATUS_STALE_AFTER_MS = 15_000
SHUTDOWN_MQTT_PUBLISH_TIMEOUT = 2.0
BLE_DISCONNECT_TIMEOUT = 2.0
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_RIG_NAME_ENV = "RIG_NAME"
DEFAULT_SPARKPLUG_GROUP_ID_ENV = "SPARKPLUG_GROUP_ID"
DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV = "SPARKPLUG_EDGE_NODE_ID"
DEFAULT_CLOUDWATCH_LOG_GROUP_ENV = "CLOUDWATCH_LOG_GROUP"
MQTT_RETRYABLE_CLEAN_SESSION_ERROR = "AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"
MQTT_RETRYABLE_UNEXPECTED_HANGUP_ERROR = "AWS_ERROR_MQTT_UNEXPECTED_HANGUP"
SPARKPLUG_SHADOW_NAME = "sparkplug"
MCU_SHADOW_NAME = "mcu"
BOARD_SHADOW_NAME = "board"
MCP_SHADOW_NAME = "mcp"
VIDEO_SHADOW_NAME = "video"
KNOWN_NAMED_SHADOWS = (
    SPARKPLUG_SHADOW_NAME,
    MCU_SHADOW_NAME,
    BOARD_SHADOW_NAME,
    MCP_SHADOW_NAME,
    VIDEO_SHADOW_NAME,
)

LOGGER = logging.getLogger("rig.ble_bridge")


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


def _is_retryable_bootstrap_mqtt_error(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return False
    message = str(error)
    return (
        MQTT_RETRYABLE_CLEAN_SESSION_ERROR in message
        or MQTT_RETRYABLE_UNEXPECTED_HANGUP_ERROR in message
    )


def _is_expected_disconnect_error(err: Exception) -> bool:
    if isinstance(err, EOFError):
        return True
    if isinstance(err, BleakDBusError):
        return err.dbus_error in {
            "org.bluez.Error.DoesNotExist",
            "org.bluez.Error.NotConnected",
            "org.bluez.Error.Failed",
        }
    return False


def _is_expected_post_sleep_confirmation_error(err: Exception) -> bool:
    if isinstance(err, (EOFError, TimeoutError)):
        return True
    if isinstance(err, BleakDBusError):
        if err.dbus_error in {
            "org.bluez.Error.DoesNotExist",
            "org.bluez.Error.NotConnected",
        }:
            return True
        if err.dbus_error == "org.bluez.Error.Failed":
            return "ATT error: 0x0e" in str(err)
    if isinstance(err, BleakError):
        message = str(err).lower()
        return (
            "disconnected" in message
            or "not found" in message
            or "att error: 0x0e" in message
        )
    if isinstance(err, RuntimeError):
        message = str(err).lower()
        return "failed to discover services" in message and "disconnected" in message
    return False


def _is_expected_post_wake_confirmation_error(err: Exception) -> bool:
    if isinstance(err, (EOFError, TimeoutError)):
        return True
    if isinstance(err, BleakDBusError):
        if err.dbus_error in {
            "org.bluez.Error.DoesNotExist",
            "org.bluez.Error.NotConnected",
            "org.bluez.Error.Failed",
        }:
            return True
    if isinstance(err, BleakError):
        message = str(err).lower()
        return (
            "disconnected" in message
            or "not found" in message
            or "att error: 0x0e" in message
        )
    return False


def _is_retryable_gatt_write_error(err: Exception) -> bool:
    if isinstance(err, BleakDBusError):
        return err.dbus_error == "org.bluez.Error.Failed" and "ATT error: 0x0e" in str(
            err
        )
    return False


def _default_cloudwatch_log_stream(thing_name: str) -> str:
    hostname = socket.gethostname().split(".", 1)[0] or "rig"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{thing_name}-{hostname}-{timestamp}-{os.getpid()}"


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _resolve_sparkplug_edge_node_id(
    *,
    rig_name: str,
    sparkplug_edge_node_id: str,
) -> str:
    normalized_rig_name = rig_name.strip()
    normalized_edge_node_id = sparkplug_edge_node_id.strip()
    if normalized_rig_name:
        return normalized_rig_name
    if normalized_edge_node_id:
        return normalized_edge_node_id
    return DEFAULT_SPARKPLUG_EDGE_NODE_ID


def _default_board_video_channel_name(thing_name: str) -> str:
    return f"{thing_name}-board-video"


def _resolve_cloudwatch_region(
    cloudwatch_region: str | None,
    *,
    aws_region: str,
) -> str | None:
    if cloudwatch_region:
        region = cloudwatch_region.strip()
        if region:
            return region
    region = aws_region.strip()
    return region or None


def _probe_cloudwatch_stream(
    logs_client: Any,
    *,
    log_group_name: str,
    log_stream_name: str,
) -> str | None:
    try:
        logs_client.create_log_group(logGroupName=log_group_name)
    except BotoClientError as err:
        error = err.response.get("Error", {})
        code = error.get("Code", "Unknown")
        if code != "ResourceAlreadyExistsException":
            return (
                f"CloudWatch log group preflight failed ({code}): "
                f"{error.get('Message', str(err))}"
            )
    except Exception as err:
        return f"CloudWatch log group preflight failed: {err}"

    try:
        logs_client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=DEFAULT_LOG_RETENTION_DAYS,
        )
    except BotoClientError as err:
        error = err.response.get("Error", {})
        code = error.get("Code", "Unknown")
        return (
            f"CloudWatch retention preflight failed ({code}): "
            f"{error.get('Message', str(err))}"
        )
    except Exception as err:
        return f"CloudWatch retention preflight failed: {err}"

    try:
        logs_client.create_log_stream(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
        )
    except BotoClientError as err:
        error = err.response.get("Error", {})
        code = error.get("Code", "Unknown")
        if code == "ResourceAlreadyExistsException":
            return None
        return (
            f"CloudWatch log stream preflight failed ({code}): "
            f"{error.get('Message', str(err))}"
        )
    except Exception as err:
        return f"CloudWatch log stream preflight failed: {err}"
    return None


def _resolve_cloudwatch_log_group_name(
    *,
    aws_runtime: AwsRuntime,
    configured_log_group: str,
    sparkplug_group_id: str,
    rig_name: str,
) -> str:
    log_group_name = configured_log_group.strip()
    if log_group_name:
        return log_group_name
    registry = AwsDeviceRegistry(aws_runtime)
    town_registration = registry.describe_town_by_name(sparkplug_group_id)
    rig_registration = registry.describe_rig_by_name(
        town_name=sparkplug_group_id,
        rig_name=rig_name,
    )
    return build_rig_log_group_name(
        town_thing_name=town_registration.thing_name,
        rig_thing_name=rig_registration.thing_name,
    )


@dataclass(slots=True, frozen=True)
class BleGattUuids:
    service_uuid: str
    sleep_command_uuid: str
    state_report_uuid: str
    device_id: str | None = None

    def with_device_id(self, device_id: str | None) -> BleGattUuids:
        normalized_device_id = (
            str(device_id).strip() if device_id is not None else None
        )
        if not normalized_device_id:
            normalized_device_id = None
        return BleGattUuids(
            service_uuid=self.service_uuid,
            sleep_command_uuid=self.sleep_command_uuid,
            state_report_uuid=self.state_report_uuid,
            device_id=normalized_device_id,
        )


DEFAULT_BLE_GATT_UUIDS = BleGattUuids(
    service_uuid=TXING_SERVICE_UUID,
    sleep_command_uuid=SLEEP_COMMAND_UUID,
    state_report_uuid=STATE_REPORT_UUID,
)


def _normalize_uuid(value: Any) -> str | None:
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value).strip()
    if not text:
        return None
    try:
        return str(UUID(text)).lower()
    except ValueError:
        return None


def _extract_reported_mcu(payload: dict[str, Any]) -> dict[str, Any] | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    reported = state.get("reported")
    if not isinstance(reported, dict):
        return None
    device = reported.get("device")
    if not isinstance(device, dict):
        return None
    mcu = device.get("mcu")
    return mcu if isinstance(mcu, dict) else None


def _extract_reported_root(payload: dict[str, Any]) -> dict[str, Any] | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    reported = state.get("reported")
    return reported if isinstance(reported, dict) else None


def _extract_reported_board(payload: dict[str, Any]) -> dict[str, Any] | None:
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    reported = state.get("reported")
    if not isinstance(reported, dict):
        return None
    device = reported.get("device")
    if not isinstance(device, dict):
        return None
    board = device.get("board")
    return board if isinstance(board, dict) else None


def _extract_reported_board_power(payload: dict[str, Any]) -> bool | None:
    board = _extract_reported_board(payload)
    if board is None:
        return None
    value = board.get("power")
    return value if isinstance(value, bool) else None


def _extract_reported_board_wifi_online(payload: dict[str, Any]) -> bool | None:
    board = _extract_reported_board(payload)
    if board is None:
        return None
    wifi = board.get("wifi")
    if not isinstance(wifi, dict):
        return None
    value = wifi.get("online")
    return value if isinstance(value, bool) else None


def _extract_reported_online(payload: dict[str, Any]) -> bool | None:
    mcu = _extract_reported_mcu(payload)
    if mcu is None:
        return None
    value = mcu.get("online")
    return value if isinstance(value, bool) else None


def _extract_reported_ble_device_id(payload: dict[str, Any]) -> str | None:
    mcu = _extract_reported_mcu(payload)
    if mcu is None:
        return None
    return _normalize_device_id(mcu.get("bleDeviceId"))


def _normalize_device_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _extract_reported_power(payload: dict[str, Any]) -> bool | None:
    mcu = _extract_reported_mcu(payload)
    if mcu is None:
        return None
    value = mcu.get("power")
    return value if isinstance(value, bool) else None


def _extract_reported_battery_mv(payload: dict[str, Any]) -> int | None:
    reported = _extract_reported_root(payload)
    if reported is None:
        return None
    device = reported.get("device")
    if not isinstance(device, dict):
        return None
    value = device.get("batteryMv")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 10000:
        return value
    return None


def _extract_shadow_version(payload: dict[str, Any]) -> int | None:
    value = payload.get("version")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _reported_from_named_shadow(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state")
    if not isinstance(state, dict):
        return {}
    reported = state.get("reported")
    return reported if isinstance(reported, dict) else {}


def _combine_named_shadow_snapshots(
    snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sparkplug = _reported_from_named_shadow(
        snapshots.get(SPARKPLUG_SHADOW_NAME, {})
    )
    sparkplug_metrics = sparkplug.get("metrics")
    if not isinstance(sparkplug_metrics, dict):
        sparkplug_metrics = {}
    mcu = _reported_from_named_shadow(snapshots.get(MCU_SHADOW_NAME, {}))
    board = _reported_from_named_shadow(snapshots.get(BOARD_SHADOW_NAME, {}))
    return {
        "state": {
            "reported": {
                "device": {
                    "batteryMv": sparkplug_metrics.get("batteryMv"),
                    "mcu": mcu,
                    "board": board,
                },
            }
        }
    }


def _calculate_redcon(
    *,
    ble_online: bool,
    mcu_power: bool,
    mcp_available: bool,
    board_video_ready: bool,
) -> int:
    if not ble_online:
        return 4
    if not mcu_power:
        return 4
    if not mcp_available:
        return 3
    if not board_video_ready:
        return 2
    return 1


@dataclass(slots=True, frozen=True)
class McpSummary:
    available: bool
    transport: str
    mcp_protocol_version: str
    descriptor_topic: str
    lease_required: bool
    lease_ttl_ms: int
    server_version: str


def _build_default_mcp_summary(thing_name: str) -> McpSummary:
    return McpSummary(
        available=False,
        transport=MCP_TRANSPORT,
        mcp_protocol_version=MCP_PROTOCOL_VERSION,
        descriptor_topic=build_mcp_descriptor_topic(thing_name),
        lease_required=True,
        lease_ttl_ms=MCP_DEFAULT_LEASE_TTL_MS,
        server_version="unknown",
    )


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default


def _coerce_non_empty_str(value: Any, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _derive_mcp_summary(
    *,
    thing_name: str,
    descriptor_payload: dict[str, Any] | None,
    status_payload: dict[str, Any] | None,
) -> McpSummary:
    defaults = _build_default_mcp_summary(thing_name)
    descriptor = descriptor_payload if isinstance(descriptor_payload, dict) else {}
    status = status_payload if isinstance(status_payload, dict) else {}

    return McpSummary(
        available=_coerce_bool(status.get("available"), default=False),
        transport=_coerce_non_empty_str(descriptor.get("transport"), default=defaults.transport),
        mcp_protocol_version=_coerce_non_empty_str(
            descriptor.get("mcpProtocolVersion"),
            default=defaults.mcp_protocol_version,
        ),
        descriptor_topic=_coerce_non_empty_str(
            descriptor.get("descriptorTopic"),
            default=defaults.descriptor_topic,
        ),
        lease_required=_coerce_bool(descriptor.get("leaseRequired"), default=defaults.lease_required),
        lease_ttl_ms=_coerce_positive_int(descriptor.get("leaseTtlMs"), default=defaults.lease_ttl_ms),
        server_version=_coerce_non_empty_str(
            descriptor.get("serverVersion"),
            default=defaults.server_version,
        ),
    )


def _build_mcp_shadow_report(
    *,
    descriptor_payload: dict[str, Any] | None,
    status_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "descriptor": descriptor_payload if isinstance(descriptor_payload, dict) else None,
        "status": (
            status_payload
            if isinstance(status_payload, dict)
            else build_mcp_status_payload(
                available=False,
                updated_at_ms=0,
            )
        ),
    }


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _coerce_optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_video_status(value: Any, *, default: str) -> str:
    if value in {VIDEO_STATUS_READY, "starting", "error", VIDEO_STATUS_UNAVAILABLE}:
        return str(value)
    return default


@dataclass(slots=True)
class BoardVideoState:
    service_id: str = VIDEO_SERVICE_NAME
    server_name: str = VIDEO_SERVICE_NAME
    available: bool = False
    ready: bool = False
    status: str = VIDEO_STATUS_UNAVAILABLE
    transport: str = VIDEO_TRANSPORT
    codec_video: str | None = VIDEO_DEFAULT_CODEC
    viewer_connected: bool = False
    last_error: str | None = None
    updated_at_ms: int | None = None
    topic_root: str = ""
    descriptor_topic: str = ""
    status_topic: str = ""
    channel_name: str = ""
    region: str | None = None
    server_version: str = "unknown"

    def apply_defaults(self, *, thing_name: str, aws_region: str) -> None:
        topics = build_video_topics(thing_name)
        if not self.server_name:
            self.server_name = VIDEO_SERVICE_NAME
        if not self.topic_root:
            self.topic_root = topics.topic_root
        if not self.descriptor_topic:
            self.descriptor_topic = topics.descriptor
        if not self.status_topic:
            self.status_topic = topics.status
        if not self.channel_name:
            self.channel_name = _default_board_video_channel_name(thing_name)
        if self.region is None and aws_region:
            self.region = aws_region
        if not self.transport:
            self.transport = VIDEO_TRANSPORT
        if self.codec_video is None:
            self.codec_video = VIDEO_DEFAULT_CODEC

    def is_fresh(self, now_ms: int, *, stale_after_ms: int = DEFAULT_VIDEO_STATUS_STALE_AFTER_MS) -> bool:
        if self.updated_at_ms is None:
            return False
        return (now_ms - self.updated_at_ms) <= stale_after_ms

    def is_ready_for_redcon(
        self,
        now_ms: int,
        *,
        stale_after_ms: int = DEFAULT_VIDEO_STATUS_STALE_AFTER_MS,
    ) -> bool:
        return (
            self.available
            and self.ready
            and self.status == VIDEO_STATUS_READY
            and self.is_fresh(now_ms, stale_after_ms=stale_after_ms)
        )

    def seconds_until_stale(
        self,
        now_ms: int,
        *,
        stale_after_ms: int = DEFAULT_VIDEO_STATUS_STALE_AFTER_MS,
    ) -> float | None:
        if not self.available or not self.ready or self.status != VIDEO_STATUS_READY:
            return None
        if self.updated_at_ms is None:
            return 0.0
        remaining_ms = stale_after_ms - (now_ms - self.updated_at_ms)
        return max(0.0, remaining_ms / 1000.0)

    def payload(self) -> dict[str, Any]:
        return {
            "serviceId": self.service_id,
            "serverInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "available": self.available,
            "ready": self.ready,
            "status": self.status,
            "transport": self.transport,
            "codec": {
                "video": self.codec_video,
            },
            "viewerConnected": self.viewer_connected,
            "lastError": self.last_error,
            "updatedAtMs": self.updated_at_ms,
            "topicRoot": self.topic_root,
            "descriptorTopic": self.descriptor_topic,
            "statusTopic": self.status_topic,
            "channelName": self.channel_name,
            "region": self.region,
            "serverVersion": self.server_version,
        }


def _default_board_video_state(*, thing_name: str, aws_region: str) -> BoardVideoState:
    state = BoardVideoState()
    state.apply_defaults(thing_name=thing_name, aws_region=aws_region)
    return state


def _derive_board_video_state(
    *,
    thing_name: str,
    aws_region: str,
    descriptor_payload: dict[str, Any] | None,
    status_payload: dict[str, Any] | None,
) -> BoardVideoState:
    state = _default_board_video_state(thing_name=thing_name, aws_region=aws_region)
    descriptor = descriptor_payload if isinstance(descriptor_payload, dict) else {}
    status = status_payload if isinstance(status_payload, dict) else {}

    state.service_id = VIDEO_SERVICE_NAME
    server_info = descriptor.get("serverInfo")
    if isinstance(server_info, dict):
        state.server_name = _coerce_non_empty_str(
            server_info.get("name"),
            default=state.server_name,
        )
    state.transport = _coerce_non_empty_str(descriptor.get("transport"), default=state.transport)
    state.topic_root = _coerce_non_empty_str(descriptor.get("topicRoot"), default=state.topic_root)
    state.descriptor_topic = _coerce_non_empty_str(
        descriptor.get("descriptorTopic"),
        default=state.descriptor_topic,
    )
    state.status_topic = _coerce_non_empty_str(
        descriptor.get("statusTopic"),
        default=state.status_topic,
    )
    state.channel_name = _coerce_non_empty_str(
        descriptor.get("channelName"),
        default=state.channel_name,
    )
    state.region = _coerce_optional_str(descriptor.get("region")) or state.region
    codec = descriptor.get("codec")
    if isinstance(codec, dict):
        state.codec_video = _coerce_optional_str(codec.get("video")) or state.codec_video
    state.server_version = _coerce_non_empty_str(
        descriptor.get("serverVersion"),
        default=state.server_version,
    )
    if isinstance(server_info, dict):
        state.server_version = _coerce_non_empty_str(
            server_info.get("version"),
            default=state.server_version,
        )

    state.available = _coerce_bool(status.get("available"), default=False)
    state.ready = _coerce_bool(status.get("ready"), default=False)
    state.status = _coerce_video_status(status.get("status"), default=state.status)
    state.viewer_connected = _coerce_bool(
        status.get("viewerConnected"),
        default=False,
    )
    state.last_error = _coerce_optional_str(status.get("lastError"))
    state.updated_at_ms = _coerce_optional_int(status.get("updatedAtMs"))
    return state


@dataclass(slots=True)
class BridgeConfig:
    name_fragment: str = DEFAULT_NAME_FRAGMENT
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    reconnect_delay: float = DEFAULT_RECONNECT_DELAY
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    command_ack_timeout: float = DEFAULT_COMMAND_ACK_TIMEOUT
    command_ack_poll_interval: float = DEFAULT_COMMAND_ACK_POLL_INTERVAL
    device_stale_after: float = DEFAULT_DEVICE_STALE_AFTER
    ble_online_stale_after: float = DEFAULT_BLE_ONLINE_STALE_AFTER
    ble_online_recover_after: float = DEFAULT_BLE_ONLINE_RECOVER_AFTER
    ble_online_recovery_gap: float = DEFAULT_BLE_ONLINE_RECOVERY_GAP
    advertisement_log_interval: float = DEFAULT_ADVERTISEMENT_LOG_INTERVAL
    scan_mode: str = DEFAULT_SCAN_MODE
    shadow_file: Path = DEFAULT_SHADOW_FILE
    lock_file: Path = DEFAULT_LOCK_FILE
    thing_name: str = DEFAULT_THING_NAME
    rig_name: str = DEFAULT_RIG_NAME
    rig_thing_name: str = ""
    sparkplug_group_id: str = DEFAULT_SPARKPLUG_GROUP_ID
    sparkplug_edge_node_id: str = DEFAULT_SPARKPLUG_EDGE_NODE_ID
    iot_endpoint: str = ""
    aws_region: str = ""
    client_id: str = ""
    aws_connect_timeout: float = DEFAULT_AWS_CONNECT_TIMEOUT
    board_offline_timeout: float = DEFAULT_BOARD_OFFLINE_TIMEOUT
    sparkplug_node_bdseq: int = field(default_factory=utc_timestamp_ms)


class RigBleState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    DEVICE_DETECTED = "device_detected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    COMMAND_PENDING = "command_pending"
    COMMAND_SENT = "command_sent"
    DISCONNECT = "disconnect"
    WAIT_FOR_NEXT_ADVERTISEMENT = "wait_for_next_advertisement"


@dataclass(slots=True)
class KnownBleDevice:
    device_id: str | None = None
    device: BLEDevice | None = None
    local_name: str | None = None
    matched_by: str | None = None
    last_seen_monotonic: float | None = None
    last_advertisement_seen_monotonic: float | None = None
    online_candidate_since_monotonic: float | None = None
    last_logged_seen_monotonic: float | None = None
    rssi: int | None = None

    def is_fresh(self, now: float, max_age: float) -> bool:
        return (
            self.device is not None
            and self.last_seen_monotonic is not None
            and (now - self.last_seen_monotonic) <= max_age
        )

    def update_from_advertisement(
        self,
        *,
        device: BLEDevice,
        local_name: str | None,
        matched_by: str,
        rssi: int | None,
        seen_at: float,
        recovery_gap: float,
    ) -> None:
        previous_seen_at = self.last_seen_monotonic
        if previous_seen_at is None or (seen_at - previous_seen_at) > recovery_gap:
            self.online_candidate_since_monotonic = seen_at
        elif self.online_candidate_since_monotonic is None:
            self.online_candidate_since_monotonic = previous_seen_at
        self.device_id = device.address
        self.device = device
        self.local_name = local_name
        self.matched_by = matched_by
        self.last_seen_monotonic = seen_at
        self.last_advertisement_seen_monotonic = seen_at
        self.rssi = rssi

    def should_log_sighting(self, now: float, min_interval: float) -> bool:
        if self.last_logged_seen_monotonic is None:
            self.last_logged_seen_monotonic = now
            return True
        if (now - self.last_logged_seen_monotonic) >= min_interval:
            self.last_logged_seen_monotonic = now
            return True
        return False


@dataclass(slots=True)
class ShadowState:
    target_redcon: int | None = None
    reported_power: bool = False
    battery_mv: int = DEFAULT_BATTERY_MV
    ble_uuids: BleGattUuids = DEFAULT_BLE_GATT_UUIDS
    ble_online: bool = False
    mcp_available: bool = False
    board_power: bool = False
    board_wifi_online: bool = False
    board_video: BoardVideoState | None = None
    redcon: int = 4
    redcon_one_staged: bool = False
    ble_uuid_search_mode: bool = False
    shadow_version: int | None = None
    snapshot_file: Path = DEFAULT_SHADOW_FILE
    thing_name: str = DEFAULT_THING_NAME
    aws_region: str = ""

    def __post_init__(self) -> None:
        if self.board_video is None:
            self.board_video = _default_board_video_state(
                thing_name=self.thing_name,
                aws_region=self.aws_region,
            )
        else:
            self.board_video.apply_defaults(
                thing_name=self.thing_name,
                aws_region=self.aws_region,
            )

    def set_target_redcon(self, redcon: int | None) -> None:
        self.target_redcon = redcon

    def set_reported(
        self,
        power: bool,
        battery_mv: int | None = None,
        ble_uuids: BleGattUuids | None = None,
    ) -> None:
        self.reported_power = power
        if battery_mv is not None:
            self.battery_mv = int(battery_mv)
        if ble_uuids is not None:
            self.ble_uuids = ble_uuids

    def set_ble_online(self, online: bool) -> None:
        self.ble_online = online

    def set_mcp_available(self, available: bool) -> None:
        self.mcp_available = available

    @property
    def ble_device_id(self) -> str | None:
        return self.ble_uuids.device_id

    @property
    def board_video_ready(self) -> bool:
        return self.board_video.ready

    @property
    def board_video_viewer_connected(self) -> bool:
        return self.board_video.viewer_connected

    def set_board_reported(
        self,
        *,
        power: bool | None = None,
        wifi_online: bool | None = None,
        video_ready: bool | None = None,
        video_viewer_connected: bool | None = None,
    ) -> None:
        if power is not None:
            self.board_power = power
        if wifi_online is not None:
            self.board_wifi_online = wifi_online
        if video_ready is not None:
            self.board_video.ready = video_ready
        if video_viewer_connected is not None:
            self.board_video.viewer_connected = video_viewer_connected

    def set_board_video_state(self, board_video: BoardVideoState) -> None:
        board_video.apply_defaults(
            thing_name=self.thing_name,
            aws_region=self.aws_region,
        )
        self.board_video = board_video

    def _derive_redcon(self) -> int:
        return _calculate_redcon(
            ble_online=self.ble_online,
            mcu_power=self.reported_power,
            mcp_available=self.mcp_available,
            board_video_ready=self.board_video.is_ready_for_redcon(utc_timestamp_ms()),
        )

    def reconcile_redcon(self) -> bool:
        derived_redcon = self._derive_redcon()
        if derived_redcon == 1 and self.redcon not in (1, 2):
            derived_redcon = 2
            self.redcon_one_staged = True
        else:
            self.redcon_one_staged = False
        if self.redcon == derived_redcon:
            return False
        self.redcon = derived_redcon
        return True

    def promote_redcon_after_stage(self) -> bool:
        if not self.redcon_one_staged:
            return False
        self.redcon_one_staged = False
        if self.redcon != 2:
            return False
        if self._derive_redcon() != 1:
            return False
        self.redcon = 1
        return True

    def payload(self) -> dict[str, Any]:
        reported: dict[str, Any] = {
            "redcon": self.redcon,
            "device": {
                "batteryMv": self.battery_mv,
                "mcu": {
                    "power": self.reported_power,
                    "online": self.ble_online,
                    "bleDeviceId": self.ble_device_id,
                },
                "board": {
                    "power": self.board_power,
                    "wifi": {
                        "online": self.board_wifi_online,
                    },
                },
            },
        }
        state: dict[str, dict[str, dict[str, Any]]] = {
            "reported": reported,
        }
        return {"state": state}

    def clear_target_redcon_if_converged(self) -> bool:
        target = self.target_redcon
        if target is None:
            return False
        if target == 4 and self.redcon == 4:
            return True
        if target < 4 and self.redcon <= target:
            return True
        return False

    def report_bytes(self) -> bytes:
        battery_mv = max(0, min(int(self.battery_mv), 0xFFFF))
        return bytes(
            (
                0x01 if not self.reported_power else 0x00,
                battery_mv & 0xFF,
                (battery_mv >> 8) & 0xFF,
            )
        )

    def log_state(self, context: str) -> None:
        LOGGER.info("%s shadow=%s", context, json.dumps(self.payload(), sort_keys=True))


@dataclass(slots=True)
class AwsShadowUpdate:
    thing_name: str
    source: str
    command_redcon: int | None = None
    reported_power: bool | None = None
    reported_online: bool | None = None
    ble_device_id_present: bool = False
    ble_device_id: str | None = None
    battery_mv: int | None = None
    board_power: bool | None = None
    board_wifi_online: bool | None = None
    mcp_descriptor: dict[str, Any] | None = None
    mcp_status: dict[str, Any] | None = None
    video_descriptor: dict[str, Any] | None = None
    video_status: dict[str, Any] | None = None
    version: int | None = None

class AwsShadowClient:
    def __init__(self, config: BridgeConfig, aws_runtime: AwsRuntime) -> None:
        self._config = config
        node_death_topic = build_node_topic(
            config.sparkplug_group_id,
            "NDEATH",
            config.sparkplug_edge_node_id,
        )
        node_death_payload = build_node_death_payload(
            bdseq=config.sparkplug_node_bdseq,
        )
        self._mqtt = AwsIotWebsocketConnection(
            AwsMqttConnectionConfig(
                endpoint=config.iot_endpoint,
                client_id=config.client_id,
                region_name=config.aws_region,
                connect_timeout_seconds=config.aws_connect_timeout,
                operation_timeout_seconds=DEFAULT_MQTT_PUBLISH_TIMEOUT,
                reconnect_min_timeout_seconds=1,
                reconnect_max_timeout_seconds=30,
                keep_alive_seconds=60,
                will_topic=node_death_topic,
                will_payload=node_death_payload,
            ),
            aws_runtime=aws_runtime,
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_resumed=self._on_connection_resumed,
            on_connection_failure=self._on_connection_failure,
            on_connection_closed=self._on_connection_closed,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event: asyncio.Event | None = None
        self._updates: asyncio.Queue[AwsShadowUpdate] | None = None
        self._update_event: asyncio.Event | None = None
        self._managed_things: tuple[str, ...] = ()
        self._managed_thing_names: set[str] = set()
        self._managed_capabilities: dict[str, tuple[str, ...]] = {}
        self._initial_snapshot_futures: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
        self._bootstrap_in_progress = False
        self._bootstrap_session_reset = False

    @property
    def is_connected(self) -> bool:
        return bool(self._connected_event and self._connected_event.is_set())

    def set_managed_things(
        self,
        thing_capabilities: Mapping[str, Iterable[str]],
    ) -> None:
        managed_capabilities: dict[str, tuple[str, ...]] = {}
        for raw_thing_name, raw_capabilities in thing_capabilities.items():
            thing_name = raw_thing_name.strip()
            if not thing_name:
                continue
            capabilities = tuple(
                capability.strip()
                for capability in raw_capabilities
                if capability.strip()
            )
            if not capabilities:
                raise RuntimeError(
                    f"Thing {thing_name!r} has no named shadow capabilities"
                )
            unsupported = [
                capability
                for capability in capabilities
                if capability not in KNOWN_NAMED_SHADOWS
            ]
            if unsupported:
                raise RuntimeError(
                    f"Thing {thing_name!r} has unsupported named shadow capabilities: "
                    f"{', '.join(unsupported)}"
                )
            managed_capabilities[thing_name] = capabilities
        unique = tuple(sorted(managed_capabilities))
        self._managed_things = unique
        self._managed_thing_names = set(unique)
        self._managed_capabilities = {
            thing_name: managed_capabilities[thing_name]
            for thing_name in unique
        }

    async def connect(self, timeout_seconds: float) -> None:
        self._loop = asyncio.get_running_loop()
        self._connected_event = asyncio.Event()
        self._updates = asyncio.Queue()
        self._update_event = asyncio.Event()
        self._initial_snapshot_futures = {}
        try:
            await self._mqtt.connect(timeout_seconds=timeout_seconds)
            self._connected_event.set()
            _log_important(
                LOGGER,
                "Connected to AWS IoT endpoint=%s rig=%s client_id=%s managed_things=%s",
                self._config.iot_endpoint,
                self._config.rig_name,
                self._config.client_id,
                len(self._managed_things),
            )
            await self._subscribe_topics(timeout_seconds=timeout_seconds)
        except Exception:
            await self.disconnect()
            raise

    async def connect_and_get_initial_snapshots(
        self,
        thing_capabilities: Mapping[str, Iterable[str]],
        timeout_seconds: float,
    ) -> dict[str, dict[str, Any]]:
        self.set_managed_things(thing_capabilities)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        self._bootstrap_in_progress = True
        try:
            while True:
                self._bootstrap_session_reset = False
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(
                        "timed out waiting for initial AWS IoT shadow snapshots"
                    )
                try:
                    await self.connect(remaining)
                    if not self._managed_things:
                        return {}

                    assert self._loop is not None
                    self._initial_snapshot_futures = {
                        (thing_name, shadow_name): self._loop.create_future()
                        for thing_name in self._managed_things
                        for shadow_name in self._managed_capabilities[thing_name]
                    }
                    for thing_name in self._managed_things:
                        for shadow_name in self._managed_capabilities[thing_name]:
                            remaining = deadline - self._loop.time()
                            if remaining <= 0:
                                raise TimeoutError(
                                    "timed out waiting for initial AWS IoT shadow snapshots"
                                )
                            await self._request_shadow_get(thing_name, shadow_name)

                    snapshots: dict[str, dict[str, Any]] = {}
                    named_snapshots: dict[str, dict[str, dict[str, Any]]] = {
                        thing_name: {} for thing_name in self._managed_things
                    }
                    for (thing_name, shadow_name), future in self._initial_snapshot_futures.items():
                        remaining = deadline - self._loop.time()
                        if remaining <= 0:
                            raise TimeoutError(
                                "timed out waiting for initial AWS IoT shadow snapshots"
                            )
                        named_snapshots[thing_name][shadow_name] = await asyncio.wait_for(
                            asyncio.shield(future),
                            timeout=remaining,
                        )
                    for thing_name, thing_snapshots in named_snapshots.items():
                        snapshots[thing_name] = _combine_named_shadow_snapshots(thing_snapshots)
                    return snapshots
                except Exception as err:
                    if not self._should_retry_bootstrap(err):
                        raise
                    retry_delay = min(
                        self._config.reconnect_delay,
                        max(0.0, deadline - loop.time()),
                    )
                    LOGGER.warning(
                        "AWS IoT shadow bootstrap was interrupted (%s); retrying initial subscribe/get in %.1fs",
                        err,
                        retry_delay,
                    )
                    if self.is_connected:
                        await self.disconnect()
                    if retry_delay > 0:
                        await asyncio.sleep(retry_delay)
                finally:
                    self._initial_snapshot_futures = {}
        finally:
            self._bootstrap_in_progress = False

    async def disconnect(self) -> None:
        try:
            await self._mqtt.disconnect(timeout_seconds=self._config.aws_connect_timeout)
        except Exception:
            pass
        if self._connected_event is not None:
            self._connected_event.clear()

    def drain_updates(self) -> list[AwsShadowUpdate]:
        if self._updates is None:
            return []
        updates: list[AwsShadowUpdate] = []
        while True:
            try:
                updates.append(self._updates.get_nowait())
            except asyncio.QueueEmpty:
                break
        if self._update_event is not None:
            if self._updates.empty():
                self._update_event.clear()
                if not self._updates.empty():
                    self._update_event.set()
            else:
                self._update_event.set()
        return updates

    async def wait_for_updates(
        self,
        timeout_seconds: float | None = None,
    ) -> list[AwsShadowUpdate]:
        if self._updates is None:
            return []
        if not self._updates.empty():
            return self.drain_updates()
        if self._update_event is None:
            return []

        try:
            if timeout_seconds is None:
                await self._update_event.wait()
            else:
                await asyncio.wait_for(
                    self._update_event.wait(),
                    timeout=timeout_seconds,
                )
        except TimeoutError:
            return []

        return self.drain_updates()

    async def update_shadow(
        self,
        *,
        thing_name: str,
        reported_device_patch: dict[str, Any] | None,
        reported_root_patch: dict[str, Any] | None = None,
        publish_timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        publishes: list[tuple[str, dict[str, Any]]] = []
        if reported_device_patch is not None:
            mcu_patch = reported_device_patch.get("mcu")
            if isinstance(mcu_patch, dict) and mcu_patch:
                publishes.append((MCU_SHADOW_NAME, mcu_patch))
        if not publishes:
            return

        for shadow_name, reported in publishes:
            await self._publish_named_shadow_update(
                thing_name,
                shadow_name,
                {"state": {"reported": reported}},
                timeout_seconds=publish_timeout_seconds,
            )

    async def update_named_shadow_reported(
        self,
        *,
        thing_name: str,
        shadow_name: str,
        reported_patch: dict[str, Any],
        publish_timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        await self._publish_named_shadow_update(
            thing_name,
            shadow_name,
            {"state": {"reported": reported_patch}},
            timeout_seconds=publish_timeout_seconds,
        )

    async def publish_sparkplug(
        self,
        topic: str,
        payload: bytes,
        *,
        timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        await self._mqtt.publish(
            topic,
            payload,
            timeout_seconds=timeout_seconds,
        )

    async def _publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        await self._mqtt.publish(
            topic,
            payload_text,
            timeout_seconds=timeout_seconds,
        )

    async def _publish_named_shadow_update(
        self,
        thing_name: str,
        shadow_name: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        await self._publish_json(
            f"$aws/things/{thing_name}/shadow/name/{shadow_name}/update",
            payload,
            timeout_seconds=timeout_seconds,
        )

    async def _request_shadow_get(self, thing_name: str, shadow_name: str) -> None:
        await self._mqtt.publish(
            f"$aws/things/{thing_name}/shadow/name/{shadow_name}/get",
            "{}",
            timeout_seconds=DEFAULT_MQTT_PUBLISH_TIMEOUT,
        )

    async def _subscribe_topics(self, *, timeout_seconds: float) -> None:
        topics: list[str] = []
        for thing_name in self._managed_things:
            for shadow_name in self._managed_capabilities.get(thing_name, ()):
                topics.extend(
                    (
                        f"$aws/things/{thing_name}/shadow/name/{shadow_name}/get/accepted",
                        f"$aws/things/{thing_name}/shadow/name/{shadow_name}/get/rejected",
                        f"$aws/things/{thing_name}/shadow/name/{shadow_name}/update/accepted",
                    )
                )
            topics.extend(
                (
                    build_mcp_descriptor_topic(thing_name),
                    build_mcp_status_topic(thing_name),
                    build_video_descriptor_topic(thing_name),
                    build_video_status_topic(thing_name),
                    build_device_topic(
                        self._config.sparkplug_group_id,
                        "DCMD",
                        self._config.sparkplug_edge_node_id,
                        thing_name,
                    ),
                )
            )

        for topic in topics:
            await self._mqtt.subscribe(
                topic,
                self._on_message,
                timeout_seconds=timeout_seconds,
            )

    def _should_retry_bootstrap(self, err: Exception) -> bool:
        return self._bootstrap_session_reset or _is_retryable_bootstrap_mqtt_error(err)

    async def _resubscribe_existing_topics(self) -> None:
        response = await self._mqtt.resubscribe_existing_topics(
            timeout_seconds=self._config.aws_connect_timeout,
        )
        topics = response.get("topics", []) if isinstance(response, dict) else []
        failed_topics = [
            topic
            for topic, granted_qos in topics
            if granted_qos is None
        ]
        if failed_topics:
            raise RuntimeError(
                f"failed to resubscribe to topic(s): {', '.join(failed_topics)}"
            )

    def _schedule_coroutine(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        description: str,
    ) -> None:
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)

        def _done(done_future: Any) -> None:
            try:
                done_future.result()
            except Exception as err:
                LOGGER.error("%s: %s", description, err)

        future.add_done_callback(_done)

    def _on_connection_interrupted(self, error: Exception) -> None:
        LOGGER.warning("AWS IoT MQTT over WebSocket interrupted: %s", error)
        if self._loop and self._connected_event:
            self._loop.call_soon_threadsafe(self._connected_event.clear)

    def _on_connection_resumed(self, return_code: Any, session_present: bool) -> None:
        _log_important(
            LOGGER,
            "AWS IoT MQTT over WebSocket resumed (return_code=%s session_present=%s)",
            return_code,
            session_present,
        )
        if self._loop and self._connected_event:
            self._loop.call_soon_threadsafe(self._connected_event.set)
        if not session_present:
            if self._bootstrap_in_progress:
                self._bootstrap_session_reset = True
                LOGGER.warning(
                    "AWS IoT MQTT session reset during initial shadow bootstrap; restarting bootstrap subscriptions"
                )
                return
            self._schedule_coroutine(
                self._resubscribe_existing_topics(),
                description="Failed to restore MQTT subscriptions after reconnect",
            )

    def _on_connection_failure(self, callback_data: Any) -> None:
        error = getattr(callback_data, "error", callback_data)
        LOGGER.error("AWS IoT MQTT over WebSocket connection failure: %s", error)

    def _on_connection_closed(self, callback_data: Any) -> None:
        reason = getattr(callback_data, "error", None)
        if reason is None:
            _log_important(LOGGER, "Disconnected from AWS IoT MQTT over WebSocket")
            return
        LOGGER.warning("AWS IoT MQTT over WebSocket closed: %s", reason)

    def _on_message(self, topic: str, payload_bytes: bytes) -> None:
        dcmd_prefix = build_node_topic(
            self._config.sparkplug_group_id,
            "DCMD",
            self._config.sparkplug_edge_node_id,
        )
        if topic.startswith(f"{dcmd_prefix}/"):
            thing_name = topic.rsplit("/", 1)[-1]
            if thing_name not in self._managed_thing_names:
                return
            try:
                command = decode_redcon_command(payload_bytes)
            except Exception as err:
                LOGGER.warning("Ignoring invalid Sparkplug DCMD payload: %s", err)
                return
            if command is None:
                LOGGER.warning(
                    "Ignoring Sparkplug DCMD without a valid redcon metric on topic %s",
                    topic,
                )
                return
            _log_important(
                LOGGER,
                "Received Sparkplug DCMD.redcon=%s thing=%s topic=%s",
                command.value,
                thing_name,
                topic,
            )
            self._enqueue_update(
                AwsShadowUpdate(
                    thing_name=thing_name,
                    source="sparkplug/dcmd",
                    command_redcon=command.value,
                )
            )
            return

        try:
            payload: dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring non-JSON payload on topic %s", topic)
            return

        mcp_topic = parse_mcp_descriptor_or_status_topic(topic)
        if mcp_topic is not None:
            thing_name, kind = mcp_topic
            if thing_name not in self._managed_thing_names:
                return
            if kind == "descriptor":
                self._enqueue_update(
                    AwsShadowUpdate(
                        thing_name=thing_name,
                        source="mqtt/mcp/descriptor",
                        mcp_descriptor=payload,
                    )
                )
                return
            self._enqueue_update(
                AwsShadowUpdate(
                    thing_name=thing_name,
                    source="mqtt/mcp/status",
                    mcp_status=payload,
                )
            )
            return

        video_topic = parse_video_descriptor_or_status_topic(topic)
        if video_topic is not None:
            thing_name, kind = video_topic
            if thing_name not in self._managed_thing_names:
                return
            if kind == "descriptor":
                self._enqueue_update(
                    AwsShadowUpdate(
                        thing_name=thing_name,
                        source="mqtt/video/descriptor",
                        video_descriptor=payload,
                    )
                )
                return
            self._enqueue_update(
                AwsShadowUpdate(
                    thing_name=thing_name,
                    source="mqtt/video/status",
                    video_status=payload,
                )
            )
            return

        parts = topic.split("/")
        if (
            len(parts) < 8
            or parts[0] != "$aws"
            or parts[1] != "things"
            or parts[3] != "shadow"
            or parts[4] != "name"
        ):
            return
        thing_name = parts[2]
        if thing_name not in self._managed_thing_names:
            return
        shadow_name = parts[5]
        if shadow_name not in self._managed_capabilities.get(thing_name, ()):
            return
        operation = "/".join(parts[6:])

        if operation == "get/rejected":
            error = RuntimeError(
                f"shadow get rejected for {thing_name}/{shadow_name}: {payload}"
            )
            LOGGER.error("%s", error)
            self._set_initial_snapshot_exception(thing_name, shadow_name, error)
            return

        if operation == "get/accepted":
            update = self._build_named_shadow_update(
                thing_name=thing_name,
                shadow_name=shadow_name,
                source="shadow/get/accepted",
                payload=payload,
            )
            self._enqueue_update(update)
            self._set_initial_snapshot(thing_name, shadow_name, payload)
            return

        if operation == "update/accepted":
            self._enqueue_update(
                self._build_named_shadow_update(
                    thing_name=thing_name,
                    shadow_name=shadow_name,
                    source="shadow/update/accepted",
                    payload=payload,
                )
            )
            return

    def _build_named_shadow_update(
        self,
        *,
        thing_name: str,
        shadow_name: str,
        source: str,
        payload: dict[str, Any],
    ) -> AwsShadowUpdate:
        reported = _reported_from_named_shadow(payload)
        update = AwsShadowUpdate(
                thing_name=thing_name,
                source=source,
                version=_extract_shadow_version(payload),
            )
        if shadow_name == SPARKPLUG_SHADOW_NAME:
            metrics = reported.get("metrics")
            value = metrics.get("batteryMv") if isinstance(metrics, dict) else None
            if not isinstance(value, bool) and isinstance(value, int) and 0 <= value <= 10000:
                update.battery_mv = value
        elif shadow_name == MCU_SHADOW_NAME:
            power = reported.get("power")
            online = reported.get("online")
            if isinstance(power, bool):
                update.reported_power = power
            if isinstance(online, bool):
                update.reported_online = online
            if "bleDeviceId" in reported:
                update.ble_device_id_present = True
                update.ble_device_id = _normalize_device_id(reported.get("bleDeviceId"))
        elif shadow_name == BOARD_SHADOW_NAME:
            power = reported.get("power")
            wifi = reported.get("wifi")
            if isinstance(power, bool):
                update.board_power = power
            if isinstance(wifi, dict) and isinstance(wifi.get("online"), bool):
                update.board_wifi_online = wifi["online"]
        return update

    def _enqueue_update(self, update: AwsShadowUpdate) -> None:
        if self._loop is None or self._updates is None:
            return

        def _put_update() -> None:
            assert self._updates is not None
            self._updates.put_nowait(update)
            if self._update_event is not None:
                self._update_event.set()

        self._loop.call_soon_threadsafe(_put_update)

    def _set_initial_snapshot(self, thing_name: str, shadow_name: str, payload: dict[str, Any]) -> None:
        if self._loop is None:
            return
        future = self._initial_snapshot_futures.get((thing_name, shadow_name))
        if future is None:
            return

        def _set() -> None:
            if not future.done():
                future.set_result(payload)

        self._loop.call_soon_threadsafe(_set)

    def _set_initial_snapshot_exception(self, thing_name: str, shadow_name: str, error: Exception) -> None:
        if self._loop is None:
            return
        future = self._initial_snapshot_futures.get((thing_name, shadow_name))
        if future is None:
            return

        def _set() -> None:
            if not future.done():
                future.set_exception(error)

        self._loop.call_soon_threadsafe(_set)


class DeviceCloudProxy:
    def __init__(self, client: AwsShadowClient, thing_name: str) -> None:
        self._client = client
        self._thing_name = thing_name

    async def update_shadow(self, **kwargs: object) -> None:
        kwargs.setdefault("thing_name", self._thing_name)
        await self._client.update_shadow(**kwargs)

    async def publish_sparkplug(
        self,
        topic: str,
        payload: bytes,
        **kwargs: object,
    ) -> None:
        await self._client.publish_sparkplug(topic, payload, **kwargs)

    async def update_named_shadow_reported(self, **kwargs: object) -> None:
        kwargs.setdefault("thing_name", self._thing_name)
        await self._client.update_named_shadow_reported(**kwargs)


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
                        f"another rig instance is already running (pid={owner_pid}, lock={self._path})"
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
        self._shadow.thing_name = config.thing_name
        self._shadow.aws_region = config.aws_region
        self._shadow.board_video.apply_defaults(
            thing_name=config.thing_name,
            aws_region=config.aws_region,
        )
        self._cloud_shadow = cloud_shadow
        self._cached_device_id: str | None = shadow.ble_uuids.device_id
        self._known_device = KnownBleDevice(device_id=self._cached_device_id)
        self._client: BleakClient | None = None
        self._scanner: BleakScanner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._advertisement_event: asyncio.Event | None = None
        self._disconnect_event: asyncio.Event | None = None
        self._ble_uuid_search_mode = shadow.ble_uuid_search_mode
        self._has_device_sync = False
        self._last_state_report: bytes | None = None
        self._require_fresh_advertisement_for_reconnect = False
        self._state = RigBleState.IDLE
        self._sparkplug_node_seq = 0
        self._sparkplug_device_seq = 0
        self._sparkplug_node_born = False
        self._sparkplug_device_born = False
        self._mcp_descriptor_payload: dict[str, Any] | None = None
        self._mcp_status_payload: dict[str, Any] | None = None
        self._video_descriptor_payload: dict[str, Any] | None = None
        self._video_status_payload: dict[str, Any] | None = None
        self._mcp_summary = _build_default_mcp_summary(config.thing_name)
        self._board_shutdown_requested_at: float | None = None
        self._board_shutdown_timeout_logged = False

    def _set_rig_state(self, next_state: RigBleState, reason: str) -> None:
        if self._state == next_state:
            LOGGER.debug("BLE state %s (%s)", next_state.value, reason)
            return
        _log_important(
            LOGGER,
            "BLE state %s -> %s (%s)",
            self._state.value,
            next_state.value,
            reason,
        )
        self._state = next_state

    def _next_sparkplug_node_seq(self) -> int:
        seq = self._sparkplug_node_seq
        self._sparkplug_node_seq = (self._sparkplug_node_seq + 1) % 256
        return seq

    def _next_sparkplug_device_seq(self) -> int:
        seq = self._sparkplug_device_seq
        self._sparkplug_device_seq = (self._sparkplug_device_seq + 1) % 256
        return seq

    @staticmethod
    def _device_label(device: BLEDevice | None, fallback_name: str | None = None) -> str:
        if device is None:
            return "<unknown>"
        name = device.name or fallback_name or "<unnamed>"
        return f"{device.address} ({name})"

    async def _publish_node_birth(self) -> None:
        await self._cloud_shadow.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NBIRTH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_birth_payload(
                redcon=1,
                bdseq=self._config.sparkplug_node_bdseq,
                seq=self._next_sparkplug_node_seq(),
            ),
        )
        self._sparkplug_node_born = True

    async def _publish_node_death(
        self,
        *,
        timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        if not self._sparkplug_node_born:
            return
        await self._cloud_shadow.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NDEATH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_death_payload(
                bdseq=self._config.sparkplug_node_bdseq,
            ),
            timeout_seconds=timeout_seconds,
        )
        self._sparkplug_node_born = False

    async def _publish_node_death_for_shutdown(self) -> None:
        death_task = asyncio.create_task(
            self._publish_node_death(
                timeout_seconds=SHUTDOWN_MQTT_PUBLISH_TIMEOUT,
            )
        )
        try:
            await asyncio.shield(death_task)
        except asyncio.CancelledError:
            await asyncio.shield(death_task)
            raise
        except Exception:
            LOGGER.exception("Failed to publish Sparkplug NDEATH during shutdown")

    async def _publish_device_birth(self) -> None:
        await self._cloud_shadow.publish_sparkplug(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DBIRTH",
                self._config.sparkplug_edge_node_id,
                self._config.thing_name,
            ),
            build_device_report_payload(
                redcon=self._shadow.redcon,
                battery_mv=self._shadow.battery_mv,
                seq=self._next_sparkplug_device_seq(),
            ),
        )
        self._sparkplug_device_born = True

    async def _publish_device_data(self) -> None:
        if not self._sparkplug_device_born:
            return
        await self._cloud_shadow.publish_sparkplug(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DDATA",
                self._config.sparkplug_edge_node_id,
                self._config.thing_name,
            ),
            build_device_report_payload(
                redcon=self._shadow.redcon,
                battery_mv=self._shadow.battery_mv,
                seq=self._next_sparkplug_device_seq(),
            ),
        )

    async def _publish_device_death(self) -> None:
        if not self._sparkplug_device_born:
            return
        await self._cloud_shadow.publish_sparkplug(
            build_device_topic(
                self._config.sparkplug_group_id,
                "DDEATH",
                self._config.sparkplug_edge_node_id,
                self._config.thing_name,
            ),
            build_device_death_payload(seq=self._next_sparkplug_device_seq()),
        )
        self._sparkplug_device_born = False

    async def _publish_static_lifecycle_reflection(self) -> None:
        return

    async def _publish_mcp_shadow_report(self) -> None:
        await self._cloud_shadow.update_named_shadow_reported(
            thing_name=self._config.thing_name,
            shadow_name=MCP_SHADOW_NAME,
            reported_patch=_build_mcp_shadow_report(
                descriptor_payload=self._mcp_descriptor_payload,
                status_payload=self._mcp_status_payload,
            ),
        )

    def _mark_ble_presence_now(self) -> None:
        loop = self._loop
        if loop is None:
            return
        now = loop.time()
        self._known_device.last_seen_monotonic = now
        if self._known_device.online_candidate_since_monotonic is None:
            self._known_device.online_candidate_since_monotonic = now

    def _ble_presence_recent(self) -> bool:
        if self._is_connected():
            return True
        loop = self._loop
        if loop is None:
            return False
        last_seen = self._known_device.last_seen_monotonic
        if last_seen is None:
            return False
        return (loop.time() - last_seen) <= self._config.ble_online_stale_after

    def _ble_online_timeout_seconds(self) -> float | None:
        if not self._shadow.ble_online or self._is_connected():
            return None
        loop = self._loop
        if loop is None:
            return None
        last_seen = self._known_device.last_seen_monotonic
        if last_seen is None:
            return 0.0
        remaining = self._config.ble_online_stale_after - (loop.time() - last_seen)
        return max(0.0, remaining)

    def _video_status_timeout_seconds(self) -> float | None:
        return self._shadow.board_video.seconds_until_stale(utc_timestamp_ms())

    def _ble_recovered_from_regular_advertising(self) -> bool:
        if self._is_connected():
            return True
        loop = self._loop
        if loop is None or not self._ble_presence_recent():
            return False
        candidate_since = self._known_device.online_candidate_since_monotonic
        if candidate_since is None:
            return False
        return (loop.time() - candidate_since) >= self._config.ble_online_recover_after

    def _target_ble_online_state(self) -> bool:
        if self._shadow.ble_online:
            return self._ble_presence_recent()
        return self._ble_recovered_from_regular_advertising()

    def _board_shutdown_wait_expired(self) -> bool:
        requested_at = self._board_shutdown_requested_at
        if requested_at is None:
            return False
        return (time.monotonic() - requested_at) >= self._config.board_offline_timeout

    async def _ensure_board_shutdown_requested(self) -> bool:
        if not self._shadow.board_power:
            return True

        if self._board_shutdown_requested_at is None:
            self._board_shutdown_requested_at = time.monotonic()
            self._board_shutdown_timeout_logged = False

        if self._board_shutdown_wait_expired() and not self._board_shutdown_timeout_logged:
            LOGGER.warning(
                "Waiting for board shutdown confirmation exceeded %.1fs during REDCON 4 convergence",
                self._config.board_offline_timeout,
            )
            self._board_shutdown_timeout_logged = True
        return False

    async def _clear_target_redcon(self, context: str) -> None:
        if self._shadow.target_redcon is None:
            return
        self._shadow.set_target_redcon(None)
        self._board_shutdown_requested_at = None
        self._board_shutdown_timeout_logged = False
        LOGGER.info("%s", context)

    def _wake_command_needed(self) -> bool:
        target_redcon = self._shadow.target_redcon
        if target_redcon is None or target_redcon == 4:
            return False
        return not (self._shadow.reported_power and self._shadow.ble_online)

    def _sleep_command_needed(self) -> bool:
        return (
            self._shadow.target_redcon == 4
            and not self._shadow.board_power
            and self._shadow.reported_power
        )

    async def _send_wake_command_for_target(self, *, context: str) -> bool:
        target_redcon = self._shadow.target_redcon
        if target_redcon is None or target_redcon == 4:
            return False
        self._set_rig_state(
            RigBleState.COMMAND_PENDING,
            f"redcon={target_redcon} requested for {self._cached_device_id or '<unknown>'} ({context})",
        )
        await self._send_sleep_command(sleep=False)
        self._set_rig_state(
            RigBleState.COMMAND_SENT,
            f"wake command written for {self._cached_device_id or '<unknown>'} ({context})",
        )
        return True

    async def _accept_wake_command_without_confirmation(
        self,
        *,
        err: Exception,
    ) -> None:
        _log_important(
            LOGGER,
            "Wake command was written but confirmation is unavailable; accepting power=true transition error=%s",
            err.__class__.__name__,
        )
        previous_redcon = self._shadow.redcon
        previous_battery = self._shadow.battery_mv
        reported_device_patch: dict[str, Any] | None = None
        if not self._shadow.reported_power:
            self._shadow.set_reported(True)
            reported_device_patch = {"mcu": {"power": True}}
        self._mark_ble_presence_now()
        await self._publish_reported_update(
            reported_device_patch=reported_device_patch,
            context="Reported synchronized after BLE wake command confirmation loss",
            previous_redcon=previous_redcon,
            previous_battery=previous_battery,
        )

    async def _accept_sleep_command_without_confirmation(
        self,
        *,
        err: Exception,
        log_message: str,
        context: str,
    ) -> None:
        _log_important(
            LOGGER,
            "%s; accepting power=false transition error=%s",
            log_message,
            err.__class__.__name__,
        )
        previous_redcon = self._shadow.redcon
        previous_battery = self._shadow.battery_mv
        reported_device_patch: dict[str, Any] | None = None
        if self._shadow.reported_power:
            self._shadow.set_reported(False)
            reported_device_patch = {"mcu": {"power": False}}
        self._mark_ble_presence_now()
        await self._publish_reported_update(
            reported_device_patch=reported_device_patch,
            context=context,
            previous_redcon=previous_redcon,
            previous_battery=previous_battery,
        )

    async def _reconcile_ble_online_presence(self) -> None:
        ble_online = self._target_ble_online_state()
        await self._publish_ble_online_state(
            online=ble_online,
            context=(
                "BLE device confirmed reachable after sustained connection or advertising"
                if ble_online
                else "BLE device offline: no connection or matching advertisement within timeout"
            ),
        )

    async def _reconcile_video_status_freshness(self) -> None:
        previous_redcon = self._shadow.redcon
        if not self._shadow.reconcile_redcon():
            return
        await self._publish_reported_update(
            reported_device_patch=None,
            context="Published derived reported.redcon after video status freshness change",
            previous_redcon=previous_redcon,
            previous_battery=self._shadow.battery_mv,
            include_redcon_if_changed=False,
        )

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._advertisement_event = asyncio.Event()
        self._disconnect_event = asyncio.Event()
        _log_important(
            LOGGER,
            "Running in hybrid BLE mode; sleep uses rendezvous, awake keeps a live connection",
        )
        if self._shadow.ble_online:
            self._mark_ble_presence_now()
            LOGGER.info(
                "Preserving reported BLE online state across startup until presence timeout or fresh advertisements prove otherwise"
            )
        await self._normalize_shadow_for_startup_default()
        await self._publish_reported_update(
            reported_device_patch=None,
            context="Synchronized reported.redcon on startup",
            include_redcon_if_changed=False,
        )
        await self._publish_static_lifecycle_reflection()
        await self._publish_node_birth()
        pending_updates = self._drain_runtime_updates()
        if pending_updates:
            await self._apply_cloud_shadow_updates(updates=pending_updates)
            pending_updates = []
        if self._shadow.ble_online:
            await self._publish_device_birth()
        await self._start_scanner()
        pending_updates = self._drain_runtime_updates()
        try:
            while True:
                if pending_updates:
                    await self._apply_cloud_shadow_updates(updates=pending_updates)
                    pending_updates = []

                if self._shadow.clear_target_redcon_if_converged():
                    await self._clear_target_redcon(
                        context="Cleared pending REDCON target after convergence",
                    )

                await self._reconcile_ble_online_presence()
                await self._reconcile_video_status_freshness()

                if not self._is_connected():
                    await self._start_scanner()
                    if self._should_idle_disconnected_while_sleeping():
                        self._set_rig_state(
                            RigBleState.IDLE,
                            "scanner armed; waiting for cloud updates, advertisements, or BLE presence timeout",
                        )
                        pending_updates = await self._wait_for_updates_or_disconnect(
                            timeout_seconds=self._ble_online_timeout_seconds(),
                            wake_on_advertisement=True,
                        )
                        continue

                    try:
                        await self._ensure_connected()
                    except asyncio.CancelledError:
                        raise
                    except Exception as err:
                        LOGGER.warning(
                            "BLE session establish failed: %s %r",
                            err.__class__.__name__,
                            err,
                        )
                        pending_updates = await self._wait_for_updates_or_disconnect(
                            timeout_seconds=self._config.reconnect_delay
                        )
                        continue

                    if self._should_idle_disconnected_while_sleeping():
                        _log_important(
                            LOGGER,
                            "MCU is in sleep mode; releasing BLE connection until power=true is requested",
                        )
                        await self._safe_disconnect()
                        continue

                try:
                    await self._process_target_redcon_once()
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    LOGGER.warning(
                        "BLE power command failed after connect: %s %r",
                        err.__class__.__name__,
                        err,
                    )
                    await self._safe_disconnect()
                    await asyncio.sleep(self._config.reconnect_delay)

                if not self._is_connected() and self._should_idle_disconnected_while_sleeping():
                    # A successful transition into sleep should restart scanning
                    # immediately so periodic rendezvous advertisements continue to
                    # maintain BLE presence.
                    continue

                retry_timeout: float | None = None
                if self._shadow.target_redcon is not None:
                    retry_timeout = self._config.reconnect_delay

                pending_updates = await self._wait_for_updates_or_disconnect(
                    timeout_seconds=retry_timeout
                )
        except asyncio.CancelledError:
            await self._publish_node_death_for_shutdown()
            raise
        finally:
            await self._stop_scanner()
            cleanup_task = asyncio.create_task(
                self._safe_disconnect(
                    publish_timeout_seconds=SHUTDOWN_MQTT_PUBLISH_TIMEOUT,
                    disconnect_timeout_seconds=BLE_DISCONNECT_TIMEOUT,
                )
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await asyncio.shield(cleanup_task)
                raise

    async def run_no_ble(self) -> None:
        _log_important(
            LOGGER,
            "Running in --no-ble mode; waiting for cloud shadow updates via MQTT",
        )
        await self._publish_ble_online_state(
            online=False,
            context="Rig startup (--no-ble): BLE disconnected",
            force=True,
        )
        await self._normalize_shadow_for_startup_default()
        await self._publish_reported_update(
            reported_device_patch=None,
            context="Synchronized reported.redcon on startup (--no-ble)",
            include_redcon_if_changed=False,
        )
        await self._publish_static_lifecycle_reflection()
        await self._publish_node_birth()
        await self._process_target_no_ble_once()
        try:
            while True:
                retry_timeout: float | None = None
                if self._shadow.target_redcon is not None:
                    retry_timeout = self._config.reconnect_delay

                updates = await self._cloud_shadow.wait_for_updates(
                    timeout_seconds=retry_timeout
                )
                await self._apply_cloud_shadow_updates(updates=updates)
                await self._process_target_no_ble_once()
        except asyncio.CancelledError:
            await self._publish_node_death_for_shutdown()
            raise

    def _drain_runtime_updates(self) -> list[AwsShadowUpdate]:
        updates = self._cloud_shadow.drain_updates()
        filtered = [update for update in updates if update.source != "shadow/get/accepted"]
        if len(filtered) != len(updates):
            LOGGER.debug(
                "Discarded %s queued startup snapshot update(s) already reflected in runtime state",
                len(updates) - len(filtered),
            )
        return filtered

    async def _normalize_shadow_for_startup_default(self) -> None:
        self._shadow.reconcile_redcon()
        if self._video_status_payload is None or not self._shadow.board_video.is_fresh(
            utc_timestamp_ms()
        ):
            self._shadow.set_board_video_state(
                _default_board_video_state(
                    thing_name=self._config.thing_name,
                    aws_region=self._config.aws_region,
                )
            )
        self._board_shutdown_requested_at = None
        self._board_shutdown_timeout_logged = False

    def _apply_mcp_mirror_update(self, update: AwsShadowUpdate) -> tuple[bool, bool]:
        descriptor_changed = False
        status_changed = False
        if update.mcp_descriptor is not None:
            descriptor_changed = self._mcp_descriptor_payload != update.mcp_descriptor
            self._mcp_descriptor_payload = update.mcp_descriptor
        if update.mcp_status is not None:
            status_changed = self._mcp_status_payload != update.mcp_status
            self._mcp_status_payload = update.mcp_status
        if not descriptor_changed and not status_changed:
            return False, False

        next_summary = _derive_mcp_summary(
            thing_name=self._config.thing_name,
            descriptor_payload=self._mcp_descriptor_payload,
            status_payload=self._mcp_status_payload,
        )
        summary_changed = next_summary != self._mcp_summary
        availability_changed = self._shadow.mcp_available != next_summary.available
        if not summary_changed and not availability_changed:
            return False, False

        self._mcp_summary = next_summary
        self._shadow.set_mcp_available(next_summary.available)
        if summary_changed:
            LOGGER.info(
                "Updated MCP shadow mirror summary thing=%s available=%s transport=%s descriptor_topic=%s lease_ttl_ms=%s",
                self._config.thing_name,
                self._mcp_summary.available,
                self._mcp_summary.transport,
                self._mcp_summary.descriptor_topic,
                self._mcp_summary.lease_ttl_ms,
            )
        return summary_changed, availability_changed

    def _apply_video_mirror_update(self, update: AwsShadowUpdate) -> tuple[bool, bool]:
        descriptor_changed = False
        status_changed = False
        if update.video_descriptor is not None:
            descriptor_changed = self._video_descriptor_payload != update.video_descriptor
            self._video_descriptor_payload = update.video_descriptor
        if update.video_status is not None:
            status_changed = self._video_status_payload != update.video_status
            self._video_status_payload = update.video_status
        if not descriptor_changed and not status_changed:
            return False, False

        previous_ready_for_redcon = self._shadow.board_video.is_ready_for_redcon(utc_timestamp_ms())
        next_state = _derive_board_video_state(
            thing_name=self._config.thing_name,
            aws_region=self._config.aws_region,
            descriptor_payload=self._video_descriptor_payload,
            status_payload=self._video_status_payload,
        )
        state_changed = next_state != self._shadow.board_video
        if not state_changed:
            return False, False

        self._shadow.set_board_video_state(next_state)
        LOGGER.info(
            "Updated video shadow mirror thing=%s available=%s ready=%s status=%s updated_at_ms=%s",
            self._config.thing_name,
            next_state.available,
            next_state.ready,
            next_state.status,
            next_state.updated_at_ms,
        )
        ready_for_redcon_changed = (
            previous_ready_for_redcon != self._shadow.board_video.is_ready_for_redcon(utc_timestamp_ms())
        )
        return True, ready_for_redcon_changed

    async def _apply_cloud_shadow_updates(
        self,
        updates: list[AwsShadowUpdate] | None = None,
    ) -> None:
        if updates is None:
            updates = self._cloud_shadow.drain_updates()
        for update in updates:
            # AWS shadow accepted snapshots can arrive after a newer local publish;
            # version-ordering prevents an older echo from reintroducing stale reported state.
            current_version = self._shadow.shadow_version
            if (
                update.version is not None
                and current_version is not None
                and update.version <= current_version
            ):
                LOGGER.debug(
                    "Ignored stale shadow update version=%s current_version=%s source=%s",
                    update.version,
                    current_version,
                    update.source,
                )
                continue

            previous_redcon = self._shadow.redcon
            previous_battery = self._shadow.battery_mv
            mcp_summary_changed, mcp_availability_changed = self._apply_mcp_mirror_update(
                update
            )
            video_shadow_changed, video_redcon_changed = self._apply_video_mirror_update(update)
            changed = False
            redcon_inputs_changed = mcp_availability_changed or video_redcon_changed
            if update.command_redcon is not None and self._shadow.target_redcon != update.command_redcon:
                _log_important(
                    LOGGER,
                    "Applying REDCON target %s -> %s (%s)",
                    self._shadow.target_redcon,
                    update.command_redcon,
                    update.source,
                )
                self._shadow.set_target_redcon(update.command_redcon)
                if update.command_redcon != 4:
                    self._board_shutdown_requested_at = None
                    self._board_shutdown_timeout_logged = False
                changed = True
            if (
                update.reported_power is not None
                and self._shadow.reported_power != update.reported_power
            ):
                self._shadow.set_reported(update.reported_power)
                changed = True
                redcon_inputs_changed = True
            if (
                update.reported_online is not None
                and self._shadow.ble_online != update.reported_online
            ):
                self._shadow.set_ble_online(update.reported_online)
                changed = True
                redcon_inputs_changed = True
            if update.ble_device_id_present and self._shadow.ble_device_id != update.ble_device_id:
                ble_uuids = self._shadow.ble_uuids.with_device_id(update.ble_device_id)
                self._shadow.set_reported(
                    self._shadow.reported_power,
                    ble_uuids=ble_uuids,
                )
                self._cached_device_id = update.ble_device_id
                self._known_device.device_id = update.ble_device_id
                changed = True
            if (
                update.battery_mv is not None
                and self._shadow.battery_mv != update.battery_mv
            ):
                self._shadow.set_reported(
                    self._shadow.reported_power,
                    battery_mv=update.battery_mv,
                )
                changed = True
            if (
                update.board_power is not None
                and self._shadow.board_power != update.board_power
            ):
                self._shadow.set_board_reported(power=update.board_power)
                if not update.board_power:
                    self._board_shutdown_requested_at = None
                changed = True
            if (
                update.board_wifi_online is not None
                and self._shadow.board_wifi_online != update.board_wifi_online
            ):
                self._shadow.set_board_reported(wifi_online=update.board_wifi_online)
                changed = True

            if (
                update.version is not None
                and (
                    self._shadow.shadow_version is None
                    or update.version > self._shadow.shadow_version
                )
            ):
                self._shadow.shadow_version = update.version

            if changed:
                self._shadow.log_state(f"Applied cloud shadow update ({update.source})")
            if mcp_summary_changed:
                await self._publish_mcp_shadow_report()
            if redcon_inputs_changed or video_shadow_changed:
                await self._publish_reported_update(
                    reported_device_patch=None,
                    context=f"Published derived reported.redcon after cloud shadow update ({update.source})",
                    previous_redcon=previous_redcon,
                    previous_battery=previous_battery,
                )

    async def _process_target_no_ble_once(self) -> None:
        target_redcon = self._shadow.target_redcon
        if target_redcon is None:
            return

        if self._shadow.clear_target_redcon_if_converged():
            await self._clear_target_redcon(
                context="Cleared pending REDCON target in --no-ble mode after convergence",
            )
            return

        if target_redcon == 4:
            if self._shadow.board_power:
                await self._ensure_board_shutdown_requested()
                return
            if self._shadow.reported_power:
                previous_redcon = self._shadow.redcon
                previous_battery = self._shadow.battery_mv
                LOGGER.info(
                    "Dry-run: would set MCU power=false over BLE for REDCON 4; updating reported in cloud"
                )
                self._shadow.set_reported(False)
                await self._publish_reported_update(
                    reported_device_patch={"mcu": {"power": False}},
                    context="Reported updated after dry-run REDCON 4 convergence",
                    previous_redcon=previous_redcon,
                    previous_battery=previous_battery,
                )
            if self._shadow.clear_target_redcon_if_converged():
                await self._clear_target_redcon(
                    context="Cleared pending REDCON target after dry-run REDCON 4 convergence",
                )
            return

        if self._shadow.reported_power:
            if self._shadow.clear_target_redcon_if_converged():
                await self._clear_target_redcon(
                    context="Cleared pending REDCON target in --no-ble mode after wake convergence",
                )
            return

        previous_redcon = self._shadow.redcon
        previous_battery = self._shadow.battery_mv
        LOGGER.info(
            "Dry-run: would wake MCU over BLE for REDCON target=%s; updating reported power=true",
            target_redcon,
        )
        self._shadow.set_reported(True)
        await self._publish_reported_update(
            reported_device_patch={"mcu": {"power": True}},
            context="Reported updated after dry-run wake convergence",
            previous_redcon=previous_redcon,
            previous_battery=previous_battery,
        )
        if self._shadow.clear_target_redcon_if_converged():
            await self._clear_target_redcon(
                context="Cleared pending REDCON target in --no-ble mode after wake convergence",
            )

    async def _process_target_redcon_once(self) -> None:
        target_redcon = self._shadow.target_redcon
        if target_redcon is None:
            return

        if self._shadow.clear_target_redcon_if_converged():
            await self._clear_target_redcon(
                context="Cleared pending REDCON target because reported.redcon already converged",
            )
            return

        if target_redcon == 4:
            if self._shadow.board_power:
                await self._ensure_board_shutdown_requested()
                return

            if not self._shadow.reported_power:
                if self._shadow.clear_target_redcon_if_converged():
                    await self._clear_target_redcon(
                        context="Cleared pending REDCON target after REDCON 4 convergence",
                    )
                return

            if not self._is_connected():
                LOGGER.info(
                    "REDCON 4 pending: BLE disconnected, waiting for reconnect before sleep command"
                )
                return

            try:
                self._set_rig_state(
                    RigBleState.COMMAND_PENDING,
                    f"redcon=4 requested for {self._cached_device_id or '<unknown>'}",
                )
                await self._send_sleep_command(sleep=True)
                self._set_rig_state(
                    RigBleState.COMMAND_SENT,
                    f"sleep command written for {self._cached_device_id or '<unknown>'}",
                )
                try:
                    report = await self._wait_for_reported_power(False)
                except Exception as err:
                    if _is_expected_post_sleep_confirmation_error(err):
                        await self._accept_sleep_command_without_confirmation(
                            err=err,
                            log_message="MCU disconnected immediately after REDCON 4 sleep command",
                            context="Reported synchronized after BLE REDCON 4 sleep command disconnect",
                        )
                        report = None
                    else:
                        raise
                if report is not None:
                    await self._sync_reported_from_state_report(
                        report,
                        context="Reported synchronized after BLE REDCON 4 command",
                        log_prefix="MCU state report after BLE REDCON 4 command",
                    )
            except Exception:
                LOGGER.exception("Failed to converge REDCON target=4; will retry")
                await self._safe_disconnect()
                return

            if self._shadow.clear_target_redcon_if_converged():
                await self._clear_target_redcon(
                    context="Cleared pending REDCON target after REDCON 4 convergence",
                )
            return

        if self._shadow.reported_power and self._shadow.ble_online:
            if self._shadow.clear_target_redcon_if_converged():
                await self._clear_target_redcon(
                    context="Cleared pending REDCON target after wake convergence",
                )
            return

        if not self._is_connected():
            LOGGER.info(
                "REDCON target pending (target=%s): BLE disconnected, waiting for reconnect",
                target_redcon,
            )
            return

        try:
            await self._send_wake_command_for_target(context="target convergence")
            try:
                report = await self._wait_for_reported_power(True)
            except Exception as err:
                if _is_expected_post_wake_confirmation_error(err):
                    await self._accept_wake_command_without_confirmation(err=err)
                    if self._shadow.clear_target_redcon_if_converged():
                        await self._clear_target_redcon(
                            context="Cleared pending REDCON target after wake command confirmation loss",
                        )
                    return
                raise
            await self._sync_reported_from_state_report(
                report,
                context="Reported synchronized after BLE REDCON wake command",
                log_prefix="MCU state report after BLE REDCON wake command",
            )
        except Exception:
            LOGGER.exception(
                "Failed to converge REDCON target=%s; will retry",
                target_redcon,
            )
            await self._safe_disconnect()
            return

        if self._shadow.clear_target_redcon_if_converged():
            await self._clear_target_redcon(
                context="Cleared pending REDCON target after wake convergence",
            )

    def _should_idle_disconnected_while_sleeping(self) -> bool:
        target_redcon = self._shadow.target_redcon
        if target_redcon is not None and target_redcon != 4:
            return False
        return not self._shadow.reported_power

    async def _start_scanner(self) -> None:
        if self._scanner is not None:
            return
        self._scanner = BleakScanner(
            detection_callback=self._handle_scan_detection,
            scanning_mode=self._config.scan_mode,
            bluez={"filters": {"DuplicateData": True}},
        )
        await self._scanner.start()
        _log_important(LOGGER, "Started BLE scanner mode=%s", self._config.scan_mode)

    async def _stop_scanner(self) -> None:
        scanner = self._scanner
        self._scanner = None
        if scanner is None:
            return
        try:
            await scanner.stop()
        except Exception:
            LOGGER.exception("Failed to stop BLE scanner cleanly")

    def _match_scan_candidate(
        self,
        device: BLEDevice,
        adv: AdvertisementData,
    ) -> str | None:
        if self._cached_device_id and device.address == self._cached_device_id:
            return "deviceId"

        configured_service_uuid = self._shadow.ble_uuids.service_uuid
        if any(
            _normalize_uuid(service) == configured_service_uuid
            for service in (adv.service_uuids or [])
        ):
            return "serviceUuid"

        name = (adv.local_name or device.name or "").lower()
        if name and self._config.name_fragment.lower() in name:
            return "name"

        mfg_data = adv.manufacturer_data or {}
        mfg = mfg_data.get(TXING_MFG_ID)
        if mfg is not None and bytes(mfg).startswith(TXING_MFG_MAGIC):
            return "manufacturer"

        return None

    @staticmethod
    def _extract_state_report_from_advertisement(
        adv: AdvertisementData,
    ) -> bytes | None:
        manufacturer_data = adv.manufacturer_data or {}
        payload = manufacturer_data.get(TXING_MFG_ID)
        if payload is None:
            return None
        payload_bytes = bytes(payload)
        if not payload_bytes.startswith(TXING_MFG_MAGIC):
            return None
        report = payload_bytes[len(TXING_MFG_MAGIC) :]
        if len(report) != 3:
            return None
        return report

    def _handle_scan_detection(
        self,
        device: BLEDevice,
        adv: AdvertisementData,
    ) -> None:
        loop = self._loop
        if loop is None:
            return

        matched_by = self._match_scan_candidate(device, adv)
        if matched_by is None:
            return
        state_report = self._extract_state_report_from_advertisement(adv)

        def _record_match() -> None:
            seen_at = loop.time()
            previous_device_id = self._known_device.device_id
            self._known_device.update_from_advertisement(
                device=device,
                local_name=adv.local_name or device.name,
                matched_by=matched_by,
                rssi=getattr(adv, "rssi", None),
                seen_at=seen_at,
                recovery_gap=self._config.ble_online_recovery_gap,
            )
            self._cached_device_id = device.address
            self._require_fresh_advertisement_for_reconnect = False
            if previous_device_id != device.address:
                _log_important(
                    LOGGER,
                    "Matched BLE advertisement deviceId=%s name=%s by=%s rssi=%s",
                    device.address,
                    adv.local_name or device.name or "<unnamed>",
                    matched_by,
                    getattr(adv, "rssi", None),
                )
            elif self._known_device.should_log_sighting(
                seen_at, self._config.advertisement_log_interval
            ):
                LOGGER.debug(
                    "Observed BLE advertisement deviceId=%s name=%s by=%s rssi=%s",
                    device.address,
                    adv.local_name or device.name or "<unnamed>",
                    matched_by,
                    getattr(adv, "rssi", None),
                )
            if self._advertisement_event is not None:
                self._advertisement_event.set()
            if state_report is not None:
                task = asyncio.create_task(
                    self._sync_reported_from_state_report(
                        state_report,
                        context="Reported synchronized from MCU advertisement state report",
                        log_prefix="MCU advertisement state report",
                    )
                )
                task.add_done_callback(self._log_background_task_error)

        loop.call_soon_threadsafe(_record_match)

    @staticmethod
    def _log_background_task_error(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.warning(
                "Background BLE task failed: %s %r",
                error.__class__.__name__,
                error,
            )

    def _get_fresh_target_device(self) -> BLEDevice | None:
        loop = self._loop
        if loop is None:
            return None
        if self._require_fresh_advertisement_for_reconnect:
            return None
        if not self._known_device.is_fresh(loop.time(), self._config.device_stale_after):
            return None
        return self._known_device.device

    async def _wait_for_advertisement_or_updates(
        self,
        *,
        timeout_seconds: float,
    ) -> tuple[list[AwsShadowUpdate], BLEDevice | None]:
        target_device = self._get_fresh_target_device()
        if target_device is not None:
            self._set_rig_state(
                RigBleState.DEVICE_DETECTED,
                f"fresh advertisement from {self._device_label(target_device, self._known_device.local_name)}",
            )
            return [], target_device

        if self._advertisement_event is None:
            raise RuntimeError("BLE advertisement event is not initialized")

        self._advertisement_event.clear()
        self._set_rig_state(
            RigBleState.SCANNING,
            f"waiting up to {timeout_seconds:.1f}s for target advertisement",
        )
        updates_task = asyncio.create_task(
            self._cloud_shadow.wait_for_updates(timeout_seconds=timeout_seconds)
        )
        advertisement_task = asyncio.create_task(self._advertisement_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {updates_task, advertisement_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if updates_task in done:
                updates = updates_task.result()
                if updates:
                    return updates, None
            if advertisement_task in done:
                target_device = self._get_fresh_target_device()
                if target_device is not None:
                    self._set_rig_state(
                        RigBleState.DEVICE_DETECTED,
                        f"advertisement from {self._device_label(target_device, self._known_device.local_name)}",
                    )
                    return [], target_device
            target_device = self._get_fresh_target_device()
            return [], target_device
        finally:
            for task in (updates_task, advertisement_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                updates_task, advertisement_task, return_exceptions=True
            )

    async def _ensure_connected(self) -> None:
        if self._is_connected():
            return

        target_device = self._get_fresh_target_device()
        if target_device is None:
            target_device = await self._wait_for_target_advertisement(
                timeout_seconds=self._config.scan_timeout
            )
        if target_device is None:
            raise RuntimeError("matching advertisement not seen before connect deadline")

        await self._stop_scanner()
        target_name = target_device.name or self._known_device.local_name or "<unnamed>"
        target_device_id = target_device.address
        client = BleakClient(
            target_device,
            disconnected_callback=self._handle_disconnect,
        )
        self._client = client
        sleep_fast_path_attempted = False
        try:
            self._set_rig_state(
                RigBleState.CONNECTING,
                self._device_label(target_device, self._known_device.local_name),
            )
            connected = await asyncio.wait_for(
                client.connect(),
                timeout=self._config.connect_timeout,
            )
            if connected is False:
                raise RuntimeError("BLE connect returned False")

            self._set_rig_state(
                RigBleState.CONNECTED,
                f"{target_device_id} ({target_name})",
            )
            self._cached_device_id = target_device_id
            self._known_device.device_id = target_device_id
            if self._wake_command_needed():
                await self._send_wake_command_for_target(
                    context="sleep rendezvous fast path",
                )
            elif self._sleep_command_needed():
                sleep_fast_path_attempted = True
                self._set_rig_state(
                    RigBleState.COMMAND_PENDING,
                    f"redcon=4 requested for {self._cached_device_id or '<unknown>'} (connect fast path)",
                )
                await self._send_sleep_command(sleep=True)
                self._set_rig_state(
                    RigBleState.COMMAND_SENT,
                    f"sleep command written for {self._cached_device_id or '<unknown>'} (connect fast path)",
                )
            await self._ensure_services_discovered(client)
            await self._resolve_ble_uuids_for_connected_client(
                client,
                device_id=target_device_id,
            )
            await self._subscribe_state_report_notifications()
            self._require_fresh_advertisement_for_reconnect = False
            self._mark_ble_presence_now()
            await self._sync_reported_from_device_on_connect()
            await self._publish_ble_online_state(
                online=True,
                context="BLE connected",
                force=True,
            )
            self._has_device_sync = True
        except Exception as err:
            if sleep_fast_path_attempted and _is_expected_post_sleep_confirmation_error(err):
                await self._safe_disconnect()
                await self._accept_sleep_command_without_confirmation(
                    err=err,
                    log_message="MCU disconnected before BLE service sync after REDCON 4 sleep command",
                    context="Reported synchronized after BLE REDCON 4 sleep command disconnect during connect",
                )
                return
            await self._safe_disconnect()
            await self._start_scanner()
            raise

    async def _publish_reported_update(
        self,
        *,
        reported_device_patch: dict[str, Any] | None,
        reported_root_patch: dict[str, Any] | None = None,
        context: str,
        publish_timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
        include_redcon_if_changed: bool = True,
        previous_redcon: int | None = None,
        previous_battery: int | None = None,
    ) -> bool:
        if reported_root_patch:
            LOGGER.debug(
                "Ignoring deprecated reported_root_patch for thing=%s keys=%s",
                self._config.thing_name,
                sorted(reported_root_patch),
            )
        redcon_changed = include_redcon_if_changed and self._shadow.reconcile_redcon()
        state_changed = (
            (previous_redcon is not None and previous_redcon != self._shadow.redcon)
            or (previous_battery is not None and previous_battery != self._shadow.battery_mv)
        )

        if (
            reported_device_patch is None
            and not redcon_changed
            and not state_changed
        ):
            return True
        try:
            if reported_device_patch is not None:
                await self._cloud_shadow.update_shadow(
                    reported_device_patch=reported_device_patch,
                    publish_timeout_seconds=publish_timeout_seconds,
                )
        except Exception:
            LOGGER.exception("Failed to publish reported shadow update; will retry")
            return False

        self._shadow.log_state(context)
        if (
            self._sparkplug_device_born
            and (
                (previous_redcon is not None and previous_redcon != self._shadow.redcon)
                or (previous_battery is not None and previous_battery != self._shadow.battery_mv)
            )
        ):
            await self._publish_device_data()
        if self._shadow.promote_redcon_after_stage():
            await self._publish_reported_update(
                reported_device_patch=None,
                context="Promoted staged REDCON 2 to REDCON 1 after MCP/video readiness confirmation",
                include_redcon_if_changed=False,
                previous_redcon=2,
                previous_battery=self._shadow.battery_mv,
            )
        return True

    async def _publish_ble_online_state(
        self,
        *,
        online: bool,
        context: str,
        force: bool = False,
        publish_timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        previous_online = self._shadow.ble_online
        if not force and previous_online == online:
            return
        previous_redcon = self._shadow.redcon
        previous_battery = self._shadow.battery_mv
        self._shadow.set_ble_online(online)
        published = await self._publish_reported_update(
            reported_device_patch={"mcu": {"online": online}},
            context=context,
            publish_timeout_seconds=publish_timeout_seconds,
            previous_redcon=previous_redcon if online else None,
            previous_battery=previous_battery if online else None,
        )
        if published and previous_online != online:
            _log_important(
                LOGGER,
                "BLE online %s -> %s (%s)",
                previous_online,
                online,
                context,
            )
            if online:
                if not self._sparkplug_device_born:
                    await self._publish_device_birth()
            else:
                await self._publish_device_death()
                if self._shadow.target_redcon is not None:
                    self._shadow.set_target_redcon(None)
                    self._board_shutdown_requested_at = None
                    self._board_shutdown_timeout_logged = False
                    LOGGER.info("Cleared pending REDCON target after DDEATH")

    async def _send_sleep_command(self, *, sleep: bool) -> None:
        if not self._is_connected():
            raise RuntimeError("BLE client is not connected")
        assert self._client is not None

        payload = b"\x01" if sleep else b"\x00"
        max_attempts = 2 if not sleep else 1
        for attempt in range(1, max_attempts + 1):
            try:
                await self._client.write_gatt_char(
                    self._shadow.ble_uuids.sleep_command_uuid,
                    payload,
                    response=True,
                )
                break
            except Exception as err:
                if attempt >= max_attempts or not _is_retryable_gatt_write_error(err):
                    raise
                LOGGER.warning(
                    "Retrying wake command after transient GATT write failure attempt=%s error=%s",
                    attempt,
                    err,
                )
                await asyncio.sleep(self._config.command_ack_poll_interval)
        LOGGER.info(
            "Sent Power Command sleep=%s power=%s via characteristic=%s",
            sleep,
            not sleep,
            self._shadow.ble_uuids.sleep_command_uuid,
        )

    @staticmethod
    def _parse_state_report(report: bytes) -> tuple[bool, bool, int]:
        if len(report) != 3:
            raise RuntimeError(
                f"unexpected State Report length: {len(report)} (expected 3)"
            )

        sleep_flag = int(report[0])
        if sleep_flag not in (0x00, 0x01):
            raise RuntimeError(f"unexpected State Report sleep byte: 0x{sleep_flag:02x}")
        sleep = sleep_flag == 0x01
        reported_power = not sleep
        battery_mv = int.from_bytes(report[1:3], byteorder="little")
        if not (0 <= battery_mv <= 10000):
            raise RuntimeError(f"unexpected battery millivolts in State Report: {battery_mv}")
        return sleep, reported_power, battery_mv

    async def _sync_reported_from_state_report(
        self,
        report: bytes,
        *,
        context: str,
        log_prefix: str,
    ) -> None:
        sleep, reported_power, battery_mv = self._parse_state_report(report)
        self._last_state_report = bytes(report)
        previous_redcon = self._shadow.redcon
        previous_battery = self._shadow.battery_mv
        power_changed = self._shadow.reported_power != reported_power
        battery_changed = self._shadow.battery_mv != battery_mv
        if not power_changed and not battery_changed:
            LOGGER.debug(
                "%s unchanged: battery_mv=%s sleep=%s => power=%s",
                log_prefix,
                battery_mv,
                sleep,
                reported_power,
            )
            return

        self._shadow.set_reported(
            power=reported_power,
            battery_mv=battery_mv,
        )
        reported_device_patch: dict[str, Any] | None = {}
        if power_changed:
            reported_device_patch["mcu"] = {"power": reported_power}
        if battery_changed:
            reported_device_patch["batteryMv"] = battery_mv
        if not reported_device_patch:
            reported_device_patch = None
        await self._publish_reported_update(
            reported_device_patch=reported_device_patch,
            context=context,
            previous_redcon=previous_redcon,
            previous_battery=previous_battery,
        )
        LOGGER.info(
            "%s: battery_mv=%s sleep=%s => power=%s",
            log_prefix,
            battery_mv,
            sleep,
            reported_power,
        )

    async def _read_state_report(self) -> bytes:
        if not self._is_connected():
            raise RuntimeError("BLE client is not connected")
        assert self._client is not None

        report = await self._client.read_gatt_char(
            self._shadow.ble_uuids.state_report_uuid
        )
        report_bytes = bytes(report)
        self._last_state_report = report_bytes
        return report_bytes

    async def _sync_reported_from_device_on_connect(self) -> None:
        if not self._is_connected():
            return
        report = await self._read_state_report()
        await self._sync_reported_from_state_report(
            report,
            context="Reported synchronized from MCU state report on connect",
            log_prefix="MCU state report on connect",
        )

    async def _subscribe_state_report_notifications(self) -> None:
        if not self._is_connected():
            return
        assert self._client is not None
        await self._client.start_notify(
            self._shadow.ble_uuids.state_report_uuid,
            self._handle_state_report_notification,
        )

    def _handle_state_report_notification(self, _: Any, data: bytearray) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._sync_reported_from_state_report(
                    bytes(data),
                    context="Reported synchronized from MCU state report notification",
                    log_prefix="MCU state report notification",
                ),
                loop,
            )
        except RuntimeError:
            LOGGER.debug(
                "Event loop already closed; skipped MCU state report notification"
            )

    def _cached_or_shadow_state_report(self, target_power: bool) -> bytes:
        report = self._last_state_report
        if report is not None:
            try:
                _sleep, reported_power, _battery_mv = self._parse_state_report(report)
            except RuntimeError:
                report = None
            else:
                if reported_power == target_power:
                    return report
        return self._shadow.report_bytes()

    async def _wait_for_reported_power(self, target_power: bool) -> bytes:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.command_ack_timeout
        per_read_timeout = 1.0

        while True:
            if self._shadow.reported_power == target_power:
                LOGGER.info(
                    "Accepted MCU power confirmation from cached state power=%s",
                    target_power,
                )
                return self._cached_or_shadow_state_report(target_power)

            remaining = deadline - loop.time()
            if remaining <= 0:
                break

            try:
                report = await asyncio.wait_for(
                    self._read_state_report(),
                    timeout=min(remaining, per_read_timeout),
                )
            except TimeoutError:
                continue
            except Exception as err:
                if self._shadow.reported_power == target_power:
                    LOGGER.info(
                        "Accepted MCU power confirmation after GATT read failure power=%s error=%s",
                        target_power,
                        err.__class__.__name__,
                    )
                    return self._cached_or_shadow_state_report(target_power)
                raise
            _sleep, reported_power, _battery_mv = self._parse_state_report(report)
            if reported_power == target_power:
                LOGGER.info("Received MCU power confirmation power=%s", target_power)
                return report

            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(self._config.command_ack_poll_interval, remaining))

        raise TimeoutError(
            f"timed out waiting for MCU power confirmation power={target_power}"
        )

    async def _ensure_services_discovered(self, client: BleakClient) -> None:
        try:
            _ = client.services
            return
        except BleakError:
            pass

        backend = getattr(client, "_backend", None)
        get_services = getattr(backend, "get_services", None)
        if callable(get_services):
            await get_services()
            return

        # Compatibility fallback for older Bleak versions.
        await client.get_services()

    async def _resolve_ble_uuids_for_connected_client(
        self,
        client: BleakClient,
        *,
        device_id: str | None,
    ) -> None:
        configured_uuids = self._shadow.ble_uuids.with_device_id(device_id)
        if (
            not self._ble_uuid_search_mode
            and self._service_has_uuid_config(client, configured_uuids)
        ):
            if configured_uuids != self._shadow.ble_uuids:
                self._shadow.set_reported(
                    self._shadow.reported_power,
                    battery_mv=self._shadow.battery_mv,
                    ble_uuids=configured_uuids,
                )
            self._known_device.device_id = configured_uuids.device_id
            LOGGER.info(
                "Validated configured BLE UUIDs: service=%s sleepCommand=%s stateReport=%s deviceId=%s",
                configured_uuids.service_uuid,
                configured_uuids.sleep_command_uuid,
                configured_uuids.state_report_uuid,
                configured_uuids.device_id or "<unknown>",
            )
            return

        if self._ble_uuid_search_mode:
            LOGGER.info("BLE UUID search mode enabled; probing GATT services")
        else:
            LOGGER.warning(
                "Configured BLE UUIDs failed validation; entering BLE UUID search mode"
            )
        self._ble_uuid_search_mode = True

        discovered_uuids = self._discover_ble_uuids_from_connected_services(client)
        if discovered_uuids is None:
            raise RuntimeError(
                "BLE UUID search mode failed: required write/read+notify characteristics not found"
            )
        discovered_uuids = discovered_uuids.with_device_id(device_id)

        if discovered_uuids != configured_uuids:
            _log_important(
                LOGGER,
                "BLE UUID search discovered service=%s sleepCommand=%s stateReport=%s deviceId=%s",
                discovered_uuids.service_uuid,
                discovered_uuids.sleep_command_uuid,
                discovered_uuids.state_report_uuid,
                discovered_uuids.device_id or "<unknown>",
            )
        else:
            LOGGER.info("BLE UUID search confirmed configured UUIDs")

        self._shadow.set_reported(
            self._shadow.reported_power,
            battery_mv=self._shadow.battery_mv,
            ble_uuids=discovered_uuids,
        )
        self._known_device.device_id = discovered_uuids.device_id
        self._ble_uuid_search_mode = False

    def _discover_ble_uuids_from_connected_services(
        self, client: BleakClient
    ) -> BleGattUuids | None:
        services = client.services
        if services is None:
            return None

        candidates: list[BleGattUuids] = []
        for service in services:
            service_uuid = _normalize_uuid(getattr(service, "uuid", None))
            if service_uuid is None:
                continue

            write_chars: list[str] = []
            state_chars: list[str] = []
            for characteristic in service.characteristics:
                char_uuid = _normalize_uuid(getattr(characteristic, "uuid", None))
                if char_uuid is None:
                    continue
                if self._characteristic_has_property(characteristic, "write"):
                    write_chars.append(char_uuid)
                if (
                    self._characteristic_has_property(characteristic, "read")
                    and self._characteristic_has_property(characteristic, "notify")
                ):
                    state_chars.append(char_uuid)

            for sleep_uuid in sorted(set(write_chars)):
                for state_uuid in sorted(set(state_chars)):
                    if sleep_uuid == state_uuid:
                        continue
                    candidates.append(
                        BleGattUuids(
                            service_uuid=service_uuid,
                            sleep_command_uuid=sleep_uuid,
                            state_report_uuid=state_uuid,
                        )
                    )

        if not candidates:
            return None

        preferred = [
            candidate
            for candidate in candidates
            if candidate.service_uuid == self._shadow.ble_uuids.service_uuid
        ]
        selected_pool = preferred or candidates
        selected_pool.sort(
            key=lambda item: (
                item.service_uuid,
                item.sleep_command_uuid,
                item.state_report_uuid,
            )
        )
        return selected_pool[0]

    def _service_has_uuid_config(self, client: BleakClient, uuids: BleGattUuids) -> bool:
        services = client.services
        if services is None:
            return False

        matched_service: Any | None = None
        for service in services:
            service_uuid = _normalize_uuid(getattr(service, "uuid", None))
            if service_uuid == uuids.service_uuid:
                matched_service = service
                break
        if matched_service is None:
            return False

        has_sleep_command = False
        has_state_report = False
        for characteristic in matched_service.characteristics:
            char_uuid = _normalize_uuid(getattr(characteristic, "uuid", None))
            if char_uuid is None:
                continue
            if (
                char_uuid == uuids.sleep_command_uuid
                and self._characteristic_has_property(characteristic, "write")
            ):
                has_sleep_command = True
            if (
                char_uuid == uuids.state_report_uuid
                and self._characteristic_has_property(characteristic, "read")
                and self._characteristic_has_property(characteristic, "notify")
            ):
                has_state_report = True

        return has_sleep_command and has_state_report

    @staticmethod
    def _characteristic_has_property(characteristic: Any, property_name: str) -> bool:
        properties = {
            str(prop).lower()
            for prop in (getattr(characteristic, "properties", None) or [])
        }
        if property_name == "write":
            return "write" in properties
        return property_name in properties

    async def _safe_disconnect(
        self,
        *,
        publish_timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
        disconnect_timeout_seconds: float | None = None,
    ) -> None:
        client = self._client
        self._client = None
        if client is None:
            self._set_rig_state(
                RigBleState.DISCONNECT,
                "closing BLE session",
            )
            return
        try:
            self._set_rig_state(
                RigBleState.DISCONNECT,
                "closing BLE session",
            )
            self._mark_ble_presence_now()
            if client.is_connected:
                disconnect_coro = client.disconnect()
                if disconnect_timeout_seconds is None:
                    await disconnect_coro
                else:
                    await asyncio.wait_for(
                        disconnect_coro,
                        timeout=disconnect_timeout_seconds,
                    )
        except TimeoutError:
            LOGGER.warning(
                "Timed out disconnecting BLE client after %.1fs; continuing shutdown",
                disconnect_timeout_seconds,
            )
        except Exception as err:
            if _is_expected_disconnect_error(err):
                LOGGER.info(
                    "BLE client was already closing during disconnect cleanup: %s %r",
                    err.__class__.__name__,
                    err,
                )
            else:
                LOGGER.exception("Failed to disconnect BLE client cleanly")

    def _handle_disconnect(self, _: BleakClient) -> None:
        LOGGER.info("BLE connection ended")
        self._require_fresh_advertisement_for_reconnect = True
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._mark_ble_presence_now)
        if loop is not None and self._disconnect_event is not None:
            loop.call_soon_threadsafe(self._disconnect_event.set)

    async def _wait_for_updates_or_disconnect(
        self,
        timeout_seconds: float | None = None,
        *,
        wake_on_advertisement: bool = False,
    ) -> list[AwsShadowUpdate]:
        video_timeout = self._video_status_timeout_seconds()
        if timeout_seconds is None:
            effective_timeout = video_timeout
        elif video_timeout is None:
            effective_timeout = timeout_seconds
        else:
            effective_timeout = min(timeout_seconds, video_timeout)
        updates_task = asyncio.create_task(
            self._cloud_shadow.wait_for_updates(timeout_seconds=effective_timeout)
        )
        disconnect_task = asyncio.create_task(self._wait_for_disconnect_event())
        advertisement_task: asyncio.Task[None] | None = None
        tasks: set[asyncio.Task[Any]] = {updates_task, disconnect_task}
        if wake_on_advertisement:
            advertisement_task = asyncio.create_task(self._wait_for_advertisement_event())
            tasks.add(advertisement_task)
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if updates_task in done:
                return updates_task.result()
            return []
        finally:
            cleanup_tasks = [updates_task, disconnect_task]
            if advertisement_task is not None:
                cleanup_tasks.append(advertisement_task)
            for task in cleanup_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    async def _wait_for_disconnect_event(self) -> None:
        if self._disconnect_event is None:
            return
        await self._disconnect_event.wait()
        self._disconnect_event.clear()

    async def _wait_for_advertisement_event(self) -> None:
        if self._advertisement_event is None:
            return
        await self._advertisement_event.wait()
        self._advertisement_event.clear()

    async def _wait_for_target_advertisement(
        self,
        *,
        timeout_seconds: float,
    ) -> BLEDevice | None:
        target_device = self._get_fresh_target_device()
        if target_device is not None:
            self._set_rig_state(
                RigBleState.DEVICE_DETECTED,
                f"fresh advertisement from {self._device_label(target_device, self._known_device.local_name)}",
            )
            return target_device

        if self._advertisement_event is None:
            raise RuntimeError("BLE advertisement event is not initialized")

        self._advertisement_event.clear()
        self._set_rig_state(
            RigBleState.SCANNING,
            f"waiting up to {timeout_seconds:.1f}s for target advertisement",
        )
        try:
            await asyncio.wait_for(
                self._advertisement_event.wait(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            self._set_rig_state(
                RigBleState.WAIT_FOR_NEXT_ADVERTISEMENT,
                "matched advertisement not seen before scan timeout",
            )
            return None

        target_device = self._get_fresh_target_device()
        if target_device is not None:
            self._set_rig_state(
                RigBleState.DEVICE_DETECTED,
                f"advertisement from {self._device_label(target_device, self._known_device.local_name)}",
            )
        return target_device

    def _is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected


@dataclass(slots=True)
class ManagedThing:
    registration: DeviceRegistration
    bridge: BleSleepBridge


def _device_snapshot_file(base_path: Path, thing_name: str) -> Path:
    if base_path.suffix:
        cache_dir = base_path.parent / base_path.stem
    else:
        cache_dir = base_path
    return cache_dir / f"{thing_name}.json"


class RigFleetBridge:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        cloud_shadow: AwsShadowClient,
        registry: AwsThingRegistryClient,
        managed_things: list[ManagedThing],
    ) -> None:
        self._config = config
        self._cloud_shadow = cloud_shadow
        self._registry = registry
        self._managed_things = managed_things
        self._managed_by_name = {
            managed.registration.thing_name: managed for managed in managed_things
        }
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scanner: BleakScanner | None = None
        self._activity_event: asyncio.Event | None = None
        self._node_born = False
        self._node_seq = 0

        for managed in self._managed_things:
            managed.bridge._start_scanner = self._noop_scanner  # type: ignore[method-assign]
            managed.bridge._stop_scanner = self._noop_scanner  # type: ignore[method-assign]

    async def _noop_scanner(self) -> None:
        return

    def _next_node_seq(self) -> int:
        seq = self._node_seq
        self._node_seq = (self._node_seq + 1) % 256
        return seq

    def _active_bridge(self) -> BleSleepBridge | None:
        for managed in self._managed_things:
            if managed.bridge._is_connected():
                return managed.bridge
        return None

    async def _publish_node_birth(self) -> None:
        await self._cloud_shadow.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NBIRTH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_birth_payload(
                redcon=1,
                bdseq=self._config.sparkplug_node_bdseq,
                seq=self._next_node_seq(),
            ),
        )
        self._node_born = True
        await self._publish_static_lifecycle_reflection()

    async def _publish_node_death(
        self,
        *,
        timeout_seconds: float = DEFAULT_MQTT_PUBLISH_TIMEOUT,
    ) -> None:
        if not self._node_born:
            return
        await self._cloud_shadow.publish_sparkplug(
            build_node_topic(
                self._config.sparkplug_group_id,
                "NDEATH",
                self._config.sparkplug_edge_node_id,
            ),
            build_node_death_payload(
                bdseq=self._config.sparkplug_node_bdseq,
            ),
            timeout_seconds=timeout_seconds,
        )
        self._node_born = False

    async def _publish_node_death_for_shutdown(self) -> None:
        death_task = asyncio.create_task(
            self._publish_node_death(
                timeout_seconds=SHUTDOWN_MQTT_PUBLISH_TIMEOUT,
            )
        )
        try:
            await asyncio.shield(death_task)
        except asyncio.CancelledError:
            await asyncio.shield(death_task)
            raise
        except Exception:
            LOGGER.exception("Failed to publish Sparkplug NDEATH during shutdown")

    async def _publish_static_lifecycle_reflection(self) -> None:
        return

    async def _start_scanner(self) -> None:
        if self._scanner is not None:
            return
        self._scanner = BleakScanner(
            detection_callback=self._handle_scan_detection,
            scanning_mode=self._config.scan_mode,
            bluez={"filters": {"DuplicateData": True}},
        )
        await self._scanner.start()
        _log_important(LOGGER, "Started shared BLE scanner mode=%s", self._config.scan_mode)

    async def _stop_scanner(self) -> None:
        scanner = self._scanner
        self._scanner = None
        if scanner is None:
            return
        try:
            await scanner.stop()
        except Exception:
            LOGGER.exception("Failed to stop shared BLE scanner cleanly")

    def _handle_scan_detection(
        self,
        device: BLEDevice,
        adv: AdvertisementData,
    ) -> None:
        exact_matches: list[BleSleepBridge] = []
        for managed in self._managed_things:
            bridge = managed.bridge
            if bridge._cached_device_id and device.address == bridge._cached_device_id:
                exact_matches.append(bridge)
        if exact_matches:
            for bridge in exact_matches:
                bridge._handle_scan_detection(device, adv)
            if self._loop is not None and self._activity_event is not None:
                self._loop.call_soon_threadsafe(self._activity_event.set)
            return

        generic_candidates: list[BleSleepBridge] = []
        single_device = len(self._managed_things) == 1
        for managed in self._managed_things:
            if managed.bridge._cached_device_id is not None and not single_device:
                continue
            matched_by = managed.bridge._match_scan_candidate(device, adv)
            if matched_by in {"serviceUuid", "name", "manufacturer"}:
                generic_candidates.append(managed.bridge)

        if len(generic_candidates) == 1:
            generic_candidates[0]._handle_scan_detection(device, adv)
            if self._loop is not None and self._activity_event is not None:
                self._loop.call_soon_threadsafe(self._activity_event.set)
        elif len(generic_candidates) > 1:
            LOGGER.debug(
                "Ignoring ambiguous BLE advertisement candidate deviceId=%s name=%s candidates=%s",
                device.address,
                adv.local_name or device.name or "<unnamed>",
                len(generic_candidates),
            )

    async def _apply_updates(self, updates: list[AwsShadowUpdate]) -> None:
        grouped: dict[str, list[AwsShadowUpdate]] = {}
        for update in updates:
            grouped.setdefault(update.thing_name, []).append(update)
        for thing_name, thing_updates in grouped.items():
            managed = self._managed_by_name.get(thing_name)
            if managed is None:
                continue
            await managed.bridge._apply_cloud_shadow_updates(updates=thing_updates)

    async def _normalize_startup(self) -> None:
        for managed in self._managed_things:
            bridge = managed.bridge
            bridge._loop = self._loop
            bridge._advertisement_event = asyncio.Event()
            bridge._disconnect_event = asyncio.Event()
            if bridge._shadow.ble_online:
                bridge._mark_ble_presence_now()
            await bridge._normalize_shadow_for_startup_default()
            await bridge._publish_reported_update(
                reported_device_patch=None,
                context=f"Synchronized reported.redcon on startup ({managed.registration.thing_name})",
                include_redcon_if_changed=False,
            )
            if bridge._shadow.ble_online:
                await bridge._publish_device_birth()

    async def _reconcile_presence(self) -> None:
        for managed in self._managed_things:
            await managed.bridge._reconcile_ble_online_presence()

    async def _clear_converged_targets(self) -> None:
        for managed in self._managed_things:
            bridge = managed.bridge
            if bridge._shadow.clear_target_redcon_if_converged():
                await bridge._clear_target_redcon(
                    context=(
                        f"Cleared pending REDCON target after convergence "
                        f"({managed.registration.thing_name})"
                    ),
                )

    def _bridge_needs_session(self, bridge: BleSleepBridge) -> bool:
        if bridge._is_connected():
            return False
        if bridge._shadow.reported_power:
            return True
        target_redcon = bridge._shadow.target_redcon
        if target_redcon is not None and not bridge._shadow.clear_target_redcon_if_converged():
            return True
        return bridge._cached_device_id is None and bridge._get_fresh_target_device() is not None

    def _select_bridge_for_session(self) -> BleSleepBridge | None:
        pending = [
            managed.bridge
            for managed in self._managed_things
            if self._bridge_needs_session(managed.bridge)
        ]
        for bridge in pending:
            if bridge._get_fresh_target_device() is not None:
                return bridge
        return pending[0] if pending else None

    async def _persist_ble_device_id_after_connect(self, managed: ManagedThing) -> None:
        bridge = managed.bridge
        current_device_id = bridge._cached_device_id
        if current_device_id is None or current_device_id == bridge._shadow.ble_device_id:
            return
        previous_redcon = bridge._shadow.redcon
        previous_battery = bridge._shadow.battery_mv
        bridge._shadow.set_reported(
            bridge._shadow.reported_power,
            ble_uuids=bridge._shadow.ble_uuids.with_device_id(current_device_id),
        )
        try:
            published = await bridge._publish_reported_update(
                reported_device_patch={"mcu": {"bleDeviceId": current_device_id}},
                context=(
                    f"Updated MCU shadow bleDeviceId "
                    f"({managed.registration.thing_name})"
                ),
                include_redcon_if_changed=False,
                previous_redcon=previous_redcon,
                previous_battery=previous_battery,
            )
        except Exception:
            LOGGER.exception(
                "Failed to update MCU shadow bleDeviceId for thing=%s deviceId=%s",
                managed.registration.thing_name,
                current_device_id,
            )
            return
        if not published:
            return
        _log_important(
            LOGGER,
            "Updated MCU shadow bleDeviceId thing=%s deviceId=%s",
            managed.registration.thing_name,
            current_device_id,
        )

    async def _connect_bridge(self, bridge: BleSleepBridge) -> None:
        if bridge._get_fresh_target_device() is None:
            await self._start_scanner()
            target_device = await bridge._wait_for_target_advertisement(
                timeout_seconds=bridge._config.scan_timeout
            )
            if target_device is None:
                raise RuntimeError("matching advertisement not seen before connect deadline")
        await self._stop_scanner()
        try:
            await bridge._ensure_connected()
        except Exception:
            await self._start_scanner()
            raise
        managed = self._managed_by_name[bridge._config.thing_name]
        await self._persist_ble_device_id_after_connect(managed)
        if not bridge._is_connected():
            await self._start_scanner()

    def _manager_timeout(self) -> float | None:
        timeouts: list[float] = []
        for managed in self._managed_things:
            for timeout in (
                managed.bridge._ble_online_timeout_seconds(),
                managed.bridge._video_status_timeout_seconds(),
            ):
                if timeout is not None:
                    timeouts.append(timeout)
        if not timeouts:
            return None
        return max(0.0, min(timeouts))

    async def _wait_for_manager_events(
        self,
        timeout_seconds: float | None,
    ) -> list[AwsShadowUpdate]:
        updates_task = asyncio.create_task(
            self._cloud_shadow.wait_for_updates(timeout_seconds=timeout_seconds)
        )
        tasks: set[asyncio.Task[Any]] = {updates_task}
        activity_task: asyncio.Task[None] | None = None
        disconnect_tasks: list[asyncio.Task[None]] = []
        if self._activity_event is not None:
            activity_task = asyncio.create_task(self._activity_event.wait())
            tasks.add(activity_task)
        for managed in self._managed_things:
            if managed.bridge._disconnect_event is None:
                continue
            disconnect_task = asyncio.create_task(managed.bridge._wait_for_disconnect_event())
            disconnect_tasks.append(disconnect_task)
            tasks.add(disconnect_task)
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if updates_task in done:
                return updates_task.result()
            return []
        finally:
            if self._activity_event is not None:
                self._activity_event.clear()
            cleanup_tasks = [updates_task]
            if activity_task is not None:
                cleanup_tasks.append(activity_task)
            cleanup_tasks.extend(disconnect_tasks)
            for task in cleanup_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._activity_event = asyncio.Event()
        await self._publish_node_birth()
        pending_updates = self._cloud_shadow.drain_updates()
        if pending_updates:
            await self._apply_updates(pending_updates)
        await self._normalize_startup()
        if self._managed_things:
            await self._start_scanner()
        pending_updates = self._cloud_shadow.drain_updates()
        try:
            while True:
                if pending_updates:
                    await self._apply_updates(pending_updates)
                    pending_updates = []

                await self._clear_converged_targets()
                await self._reconcile_presence()

                active_bridge = self._active_bridge()
                if active_bridge is not None:
                    await active_bridge._process_target_redcon_once()
                    if (
                        active_bridge._is_connected()
                        and active_bridge._should_idle_disconnected_while_sleeping()
                    ):
                        await active_bridge._safe_disconnect()
                    if not active_bridge._is_connected():
                        # Mirror the single-device path: once a session has been
                        # released, keep scanning so sleep-state rendezvous
                        # advertisements continue to maintain BLE presence.
                        await self._start_scanner()
                    pending_updates = await self._wait_for_manager_events(
                        timeout_seconds=self._manager_timeout()
                    )
                    continue

                candidate = self._select_bridge_for_session()
                if candidate is not None:
                    try:
                        await self._connect_bridge(candidate)
                    except asyncio.CancelledError:
                        raise
                    except Exception as err:
                        LOGGER.warning(
                            "BLE session establish failed thing=%s error=%s %r",
                            candidate._config.thing_name,
                            err.__class__.__name__,
                            err,
                        )
                        pending_updates = await self._wait_for_manager_events(
                            timeout_seconds=self._config.reconnect_delay
                        )
                    continue

                pending_updates = await self._wait_for_manager_events(
                    timeout_seconds=self._manager_timeout()
                )
        except asyncio.CancelledError:
            await self._publish_node_death_for_shutdown()
            raise
        finally:
            await self._stop_scanner()
            active_bridge = self._active_bridge()
            if active_bridge is not None:
                cleanup_task = asyncio.create_task(
                    active_bridge._safe_disconnect(
                        publish_timeout_seconds=SHUTDOWN_MQTT_PUBLISH_TIMEOUT,
                        disconnect_timeout_seconds=BLE_DISCONNECT_TIMEOUT,
                    )
                )
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    await asyncio.shield(cleanup_task)
                    raise

    async def run_no_ble(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._activity_event = asyncio.Event()
        await self._publish_node_birth()
        pending_updates = self._cloud_shadow.drain_updates()
        if pending_updates:
            await self._apply_updates(pending_updates)
        for managed in self._managed_things:
            bridge = managed.bridge
            await bridge._publish_ble_online_state(
                online=False,
                context=f"Rig startup (--no-ble): BLE disconnected ({managed.registration.thing_name})",
                force=True,
            )
        await self._normalize_startup()
        for managed in self._managed_things:
            await managed.bridge._process_target_no_ble_once()
        try:
            while True:
                retry_timeout = self._config.reconnect_delay if any(
                    managed.bridge._shadow.target_redcon is not None
                    for managed in self._managed_things
                ) else None
                updates = await self._cloud_shadow.wait_for_updates(
                    timeout_seconds=retry_timeout
                )
                await self._apply_updates(updates)
                for managed in self._managed_things:
                    await managed.bridge._process_target_no_ble_once()
        except asyncio.CancelledError:
            await self._publish_node_death_for_shutdown()
            raise


async def _disconnect_cloud_shadow(cloud_shadow: Any) -> None:
    disconnect_task = asyncio.create_task(cloud_shadow.disconnect())
    try:
        await asyncio.shield(disconnect_task)
    except asyncio.CancelledError:
        await asyncio.shield(disconnect_task)
        raise


async def _run_rig_service(
    *,
    args_no_ble: bool,
    config: BridgeConfig,
    aws_runtime: AwsRuntime,
    cloud_shadow_factory: Callable[[BridgeConfig, AwsRuntime], Any] = AwsShadowClient,
    registry_client_factory: Callable[[Any], Any] = AwsThingRegistryClient,
    fleet_bridge_factory: Callable[..., RigFleetBridge] = RigFleetBridge,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    while True:
        cloud_shadow: Any | None = None
        registry_client = registry_client_factory(aws_runtime.iot_client())
        rig_registration = registry_client.describe_rig_in_town(
            town_name=config.sparkplug_group_id,
            rig_name=config.rig_name,
        )
        runtime_config = replace(
            config,
            rig_thing_name=rig_registration.thing_name,
        )
        cloud_shadow = cloud_shadow_factory(runtime_config, aws_runtime)
        fleet_bridge: RigFleetBridge | None = None
        try:
            try:
                registrations = registry_client.list_rig_things(runtime_config.rig_name)
            except ThingGroupNotFoundError:
                LOGGER.warning(
                    "Dynamic thing group for rig=%s was not found; starting idle with no managed devices",
                    runtime_config.rig_name,
                )
                registrations = []
            _log_important(
                LOGGER,
                "Loaded %s registered device(s) from dynamic thing group for rig=%s",
                len(registrations),
                runtime_config.rig_name,
            )
            snapshots = await cloud_shadow.connect_and_get_initial_snapshots(
                {
                    registration.thing_name: registration.capabilities_set
                    for registration in registrations
                },
                timeout_seconds=runtime_config.aws_connect_timeout,
            )
            managed_things: list[ManagedThing] = []
            for registration in registrations:
                thing_name = registration.thing_name
                device_config = replace(
                    runtime_config,
                    thing_name=thing_name,
                    shadow_file=_device_snapshot_file(runtime_config.shadow_file, thing_name),
                )
                shadow = _build_shadow_from_snapshot(
                    snapshots[thing_name],
                    snapshot_file=device_config.shadow_file,
                    thing_name=thing_name,
                    aws_region=device_config.aws_region,
                )
                shadow.log_state(f"Initialized from AWS IoT shadow snapshot ({thing_name})")
                managed_things.append(
                    ManagedThing(
                        registration=registration,
                        bridge=BleSleepBridge(
                            device_config,
                            shadow,
                            DeviceCloudProxy(cloud_shadow, thing_name),  # type: ignore[arg-type]
                        ),
                    )
                )

            fleet_bridge = fleet_bridge_factory(
                runtime_config,
                cloud_shadow=cloud_shadow,
                registry=registry_client,
                managed_things=managed_things,
            )
            if args_no_ble:
                while True:
                    try:
                        await fleet_bridge.run_no_ble()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        LOGGER.exception(
                            "No-BLE loop failed; retrying in %.1fs",
                            runtime_config.reconnect_delay,
                        )
                        await sleep_func(runtime_config.reconnect_delay)
                continue

            while True:
                try:
                    await fleet_bridge.run()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception(
                        "BLE bridge loop failed; retrying in %.1fs",
                        runtime_config.reconnect_delay,
                    )
                    await sleep_func(runtime_config.reconnect_delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "Rig startup failed; retrying in %.1fs",
                config.reconnect_delay,
            )
            await sleep_func(config.reconnect_delay)
        finally:
            if fleet_bridge is not None:
                await fleet_bridge._publish_node_death_for_shutdown()
            if cloud_shadow is not None:
                await _disconnect_cloud_shadow(cloud_shadow)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig",
        description="Txing rig lifecycle process (AWS IoT Shadow + Sparkplug + BLE bridge)",
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
        help="Seconds to wait for the next matching BLE advertisement before connect retry (default: 12)",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help="Seconds to wait before retrying failed loops (default: 1)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT,
        help="Seconds to wait for a BLE connection attempt after a matching advertisement (default: 10)",
    )
    parser.add_argument(
        "--command-ack-timeout",
        type=float,
        default=DEFAULT_COMMAND_ACK_TIMEOUT,
        help="Seconds to wait for MCU power confirmation in the BLE state report (default: 2)",
    )
    parser.add_argument(
        "--command-ack-poll-interval",
        type=float,
        default=DEFAULT_COMMAND_ACK_POLL_INTERVAL,
        help="Seconds between state-report polls while waiting for MCU power confirmation (default: 0.1)",
    )
    parser.add_argument(
        "--device-stale-after",
        type=float,
        default=DEFAULT_DEVICE_STALE_AFTER,
        help="Seconds before a previously seen advertisement is considered stale for immediate reconnect (default: 0.75)",
    )
    parser.add_argument(
        "--ble-online-stale-after",
        type=float,
        default=DEFAULT_BLE_ONLINE_STALE_AFTER,
        help="Seconds without a matching connection or advertisement before reported.device.mcu.online becomes false (default: 30)",
    )
    parser.add_argument(
        "--ble-online-recover-after",
        type=float,
        default=DEFAULT_BLE_ONLINE_RECOVER_AFTER,
        help="Seconds of sustained BLE presence required before reported.device.mcu.online becomes true after being false (default: 4)",
    )
    parser.add_argument(
        "--ble-online-recovery-gap",
        type=float,
        default=DEFAULT_BLE_ONLINE_RECOVERY_GAP,
        help="Maximum allowed gap between consecutive advertisements while proving BLE online recovery (default: 12)",
    )
    parser.add_argument(
        "--advertisement-log-interval",
        type=float,
        default=DEFAULT_ADVERTISEMENT_LOG_INTERVAL,
        help="Minimum seconds between repeated info logs for advertisements from the same known device (default: 5)",
    )
    parser.add_argument(
        "--scan-mode",
        default=DEFAULT_SCAN_MODE,
        choices=("active", "passive"),
        help="BLE scan mode to use while waiting for advertisements from sleeping devices (default: active)",
    )
    parser.add_argument(
        "--shadow-file",
        type=Path,
        default=DEFAULT_SHADOW_FILE,
        help="Deprecated local shadow cache path (ignored; default: /tmp/txing_shadow.json)",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=DEFAULT_LOCK_FILE,
        help="Path to single-instance lock file (default: /tmp/rig.lock)",
    )
    parser.add_argument(
        "--rig-name",
        default=_env_text(DEFAULT_RIG_NAME_ENV, DEFAULT_RIG_NAME),
        help="Dynamic AWS IoT thing group name for devices assigned to this rig (default: rig)",
    )
    parser.add_argument(
        "--sparkplug-group-id",
        default=_env_text(DEFAULT_SPARKPLUG_GROUP_ID_ENV, DEFAULT_SPARKPLUG_GROUP_ID),
        help="Sparkplug group id (default: town)",
    )
    parser.add_argument(
        "--sparkplug-edge-node-id",
        default=_env_text(
            DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV,
            DEFAULT_SPARKPLUG_EDGE_NODE_ID,
        ),
        help="Sparkplug edge node id (default: rig)",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="MQTT client id (default: rig-<pid>)",
    )
    parser.add_argument(
        "--aws-connect-timeout",
        type=float,
        default=DEFAULT_AWS_CONNECT_TIMEOUT,
        help="Seconds to wait for initial AWS MQTT connect + shadow get (default: 20)",
    )
    parser.add_argument(
        "--board-offline-timeout",
        type=float,
        default=DEFAULT_BOARD_OFFLINE_TIMEOUT,
        help="Seconds to wait for reported.device.board.power=false before sleeping the MCU for REDCON 4 (default: 45)",
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
        default=_env_text(
            DEFAULT_CLOUDWATCH_LOG_GROUP_ENV,
            DEFAULT_CLOUDWATCH_LOG_GROUP,
        ),
        help=(
            "CloudWatch Logs group name for rig logs "
            "(default: auto-resolve txing/<town-thing-name>/<rig-thing-name>)"
        ),
    )
    parser.add_argument(
        "--cloudwatch-log-stream",
        default=None,
        help="CloudWatch Logs stream name (default: generated per host/process)",
    )
    parser.add_argument(
        "--cloudwatch-region",
        default=None,
        help="CloudWatch region override (default: same as AWS region)",
    )
    parser.add_argument(
        "--no-cloudwatch-logs",
        action="store_true",
        help="Disable direct CloudWatch Logs publishing",
    )
    parser.add_argument(
        "--no-ble",
        action="store_true",
        help="Do not use BLE; still sync reported lifecycle state with AWS shadow",
    )
    return parser.parse_args()


def _build_shadow_from_snapshot(
    snapshot: dict[str, Any],
    *,
    snapshot_file: Path,
    thing_name: str = DEFAULT_THING_NAME,
    aws_region: str = "",
) -> ShadowState:
    reported_power = _extract_reported_power(snapshot)
    reported_online = _extract_reported_online(snapshot)
    battery_mv = _extract_reported_battery_mv(snapshot)
    board_power = _extract_reported_board_power(snapshot)
    board_wifi_online = _extract_reported_board_wifi_online(snapshot)
    ble_uuids = DEFAULT_BLE_GATT_UUIDS.with_device_id(
        _extract_reported_ble_device_id(snapshot)
    )

    return ShadowState(
        target_redcon=None,
        reported_power=(
            reported_power if reported_power is not None else DEFAULT_REPORTED_POWER
        ),
        battery_mv=(
            battery_mv
            if battery_mv is not None
            else DEFAULT_BATTERY_MV
        ),
        ble_uuids=ble_uuids,
        ble_online=(
            reported_online
            if reported_online is not None
            else DEFAULT_REPORTED_ONLINE
        ),
        mcp_available=False,
        board_power=(
            board_power
            if board_power is not None
            else DEFAULT_BOARD_POWER
        ),
        board_wifi_online=(
            board_wifi_online
            if board_wifi_online is not None
            else DEFAULT_BOARD_WIFI_ONLINE
        ),
        board_video=_default_board_video_state(
            thing_name=thing_name,
            aws_region=aws_region,
        ),
        redcon=DEFAULT_REDCON,
        ble_uuid_search_mode=False,
        shadow_version=_extract_shadow_version(snapshot),
        snapshot_file=snapshot_file,
        thing_name=thing_name,
        aws_region=aws_region,
    )


def _configure_logging(
    args: argparse.Namespace,
    *,
    aws_region: str,
    aws_runtime: AwsRuntime | None,
) -> None:
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
            "rig start warning: watchtower dependency is not installed; "
            "CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    if boto3 is None:
        print(
            "rig start warning: boto3 dependency is not installed; "
            "CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    stream_name = args.cloudwatch_log_stream or _default_cloudwatch_log_stream(
        args.rig_name
    )
    cloudwatch_region = _resolve_cloudwatch_region(
        args.cloudwatch_region,
        aws_region=aws_region,
    )
    if not cloudwatch_region:
        print(
            "rig start warning: could not resolve CloudWatch region; "
            "CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    try:
        if aws_runtime is None:
            raise RuntimeError("AWS runtime is unavailable")
        logs_client = aws_runtime.logs_client(region_name=cloudwatch_region)
    except Exception as err:
        print(
            "rig start warning: failed to initialize CloudWatch boto3 client "
            f"(region={cloudwatch_region}): {err}; CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    preflight_error = _probe_cloudwatch_stream(
        logs_client,
        log_group_name=args.cloudwatch_log_group,
        log_stream_name=stream_name,
    )
    if preflight_error is not None:
        print(
            f"rig start warning: {preflight_error}; "
            "CloudWatch log streaming disabled",
            file=sys.stderr,
        )
        return

    try:
        cloudwatch_handler = watchtower.CloudWatchLogHandler(
            log_group_name=args.cloudwatch_log_group,
            log_stream_name=stream_name,
            boto3_client=logs_client,
            create_log_group=False,
            create_log_stream=False,
            send_interval=5,
        )
    except Exception as err:
        print(
            f"rig start warning: failed to initialize CloudWatch log handler: {err}",
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

    try:
        if boto3 is None:
            raise RuntimeError("boto3 is required for IoT registry and thing-group access")
        ensure_aws_profile("AWS_RIG_PROFILE")
        aws_region = resolve_aws_region()
        if not aws_region:
            raise RuntimeError("could not resolve AWS region for AWS IoT access")
        aws_runtime = build_aws_runtime(region_name=aws_region)
        iot_endpoint = aws_runtime.iot_data_endpoint()
    except RuntimeError as err:
        print(f"rig start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    if not args.no_cloudwatch_logs:
        try:
            args.cloudwatch_log_group = _resolve_cloudwatch_log_group_name(
                aws_runtime=aws_runtime,
                configured_log_group=args.cloudwatch_log_group,
                sparkplug_group_id=args.sparkplug_group_id,
                rig_name=args.rig_name,
            )
        except Exception as err:
            print(
                "rig start warning: failed to resolve canonical CloudWatch log group "
                f"for town={args.sparkplug_group_id} rig={args.rig_name}: {err}; "
                "CloudWatch log streaming disabled",
                file=sys.stderr,
            )
            args.no_cloudwatch_logs = True

    _configure_logging(args, aws_region=aws_region, aws_runtime=aws_runtime)

    resolved_sparkplug_edge_node_id = _resolve_sparkplug_edge_node_id(
        rig_name=args.rig_name,
        sparkplug_edge_node_id=args.sparkplug_edge_node_id,
    )
    if (
        args.sparkplug_edge_node_id.strip()
        and resolved_sparkplug_edge_node_id != args.sparkplug_edge_node_id.strip()
    ):
        LOGGER.warning(
            "Ignoring SPARKPLUG_EDGE_NODE_ID=%s and using rig identity %s for Sparkplug edge node id",
            args.sparkplug_edge_node_id,
            resolved_sparkplug_edge_node_id,
        )

    config = BridgeConfig(
        name_fragment=args.name,
        scan_timeout=args.scan_timeout,
        reconnect_delay=args.reconnect_delay,
        connect_timeout=args.connect_timeout,
        command_ack_timeout=args.command_ack_timeout,
        command_ack_poll_interval=args.command_ack_poll_interval,
        device_stale_after=args.device_stale_after,
        ble_online_stale_after=args.ble_online_stale_after,
        ble_online_recover_after=args.ble_online_recover_after,
        ble_online_recovery_gap=args.ble_online_recovery_gap,
        advertisement_log_interval=args.advertisement_log_interval,
        scan_mode=args.scan_mode,
        shadow_file=args.shadow_file,
        lock_file=args.lock_file,
        rig_name=args.rig_name,
        sparkplug_group_id=args.sparkplug_group_id,
        sparkplug_edge_node_id=resolved_sparkplug_edge_node_id,
        iot_endpoint=iot_endpoint,
        aws_region=aws_region,
        client_id=args.client_id or f"rig-{os.getpid()}",
        aws_connect_timeout=args.aws_connect_timeout,
        board_offline_timeout=args.board_offline_timeout,
    )

    lock = InstanceLock(config.lock_file)
    try:
        lock.acquire()
    except RuntimeError as err:
        print(f"rig start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    _log_important(
        LOGGER,
        "Rig started pid=%s lock=%s rig=%s",
        os.getpid(),
        config.lock_file,
        config.rig_name,
    )
    LOGGER.info(
        "AWS IoT config endpoint=%s region=%s rig=%s sparkplug_group=%s sparkplug_edge=%s client_id=%s aws_profile=%s",
        config.iot_endpoint,
        config.aws_region,
        config.rig_name,
        config.sparkplug_group_id,
        config.sparkplug_edge_node_id,
        config.client_id,
        os.getenv("AWS_PROFILE", ""),
    )

    async def _run_rig() -> None:
        await _run_rig_service(
            args_no_ble=args.no_ble,
            config=config,
            aws_runtime=aws_runtime,
        )

    async def _runner() -> None:
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()
        installed_signals: list[signal.Signals] = []

        def _request_shutdown(sig: signal.Signals) -> None:
            if shutdown_event.is_set():
                return
            _log_important(LOGGER, "Shutting down rig (signal=%s)", sig.name)
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown, sig)
            except NotImplementedError:
                LOGGER.debug("Signal handlers are not supported on this platform")
                break
            installed_signals.append(sig)

        rig_task = asyncio.create_task(_run_rig())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {rig_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if rig_task in done:
                await rig_task
                return

            rig_task.cancel()
            await asyncio.gather(rig_task, return_exceptions=True)
        finally:
            for sig in installed_signals:
                loop.remove_signal_handler(sig)
            if not shutdown_task.done():
                shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        _log_important(LOGGER, "Shutting down rig")
    finally:
        lock.release()
        logging.shutdown()
