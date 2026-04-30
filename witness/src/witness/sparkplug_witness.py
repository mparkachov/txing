from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3


LOGGER = logging.getLogger(__name__)
THING_INDEX_NAME = "AWS_Things"
SPARKPLUG_NAMESPACE = "spBv1.0"
DEVICE_MESSAGE_TYPES = {"DBIRTH", "DDATA", "DDEATH"}
NODE_MESSAGE_TYPES = {"NBIRTH", "NDATA", "NDEATH"}
REPLACE_METRICS_MESSAGE_TYPES = {"DBIRTH", "NBIRTH"}
MERGE_METRICS_MESSAGE_TYPES = {"DDATA", "NDATA"}
CLEAR_METRICS_MESSAGE_TYPES = {"DDEATH", "NDEATH"}


@dataclass(frozen=True, slots=True)
class SparkplugMessage:
    group_id: str
    message_type: str
    edge_node_id: str
    device_id: str | None
    seq: int | None
    sparkplug_timestamp: int | None
    metrics: dict[str, Any]


def _read_varint(data: bytes, start_offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    offset = start_offset
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("Sparkplug varint is too large")
    raise ValueError("Unexpected end of Sparkplug payload")


def _read_length_delimited(data: bytes, start_offset: int) -> tuple[bytes, int]:
    length, next_offset = _read_varint(data, start_offset)
    end_offset = next_offset + length
    if end_offset > len(data):
        raise ValueError("Unexpected end of Sparkplug payload")
    return data[next_offset:end_offset], end_offset


def _read_key(data: bytes, start_offset: int) -> tuple[int, int, int]:
    key, next_offset = _read_varint(data, start_offset)
    return key >> 3, key & 0x07, next_offset


def _skip_field(data: bytes, start_offset: int, wire_type: int) -> int:
    if wire_type == 0:
        _, next_offset = _read_varint(data, start_offset)
        return next_offset
    if wire_type == 1:
        return start_offset + 8
    if wire_type == 2:
        _, next_offset = _read_length_delimited(data, start_offset)
        return next_offset
    if wire_type == 5:
        return start_offset + 4
    raise ValueError(f"Unsupported Sparkplug wire type {wire_type}")


def _decode_metric(metric_bytes: bytes) -> tuple[str, Any] | None:
    offset = 0
    name = ""
    int_value: int | None = None
    long_value: int | None = None
    bool_value: bool | None = None
    string_value: str | None = None
    while offset < len(metric_bytes):
        field_number, wire_type, offset = _read_key(metric_bytes, offset)
        if field_number == 1 and wire_type == 2:
            raw_name, offset = _read_length_delimited(metric_bytes, offset)
            name = raw_name.decode("utf-8")
            continue
        if field_number == 10 and wire_type == 0:
            int_value, offset = _read_varint(metric_bytes, offset)
            continue
        if field_number == 11 and wire_type == 0:
            long_value, offset = _read_varint(metric_bytes, offset)
            continue
        if field_number == 12 and wire_type == 0:
            raw_bool, offset = _read_varint(metric_bytes, offset)
            bool_value = raw_bool != 0
            continue
        if field_number == 13 and wire_type == 2:
            raw_string, offset = _read_length_delimited(metric_bytes, offset)
            string_value = raw_string.decode("utf-8")
            continue
        offset = _skip_field(metric_bytes, offset, wire_type)

    if not name:
        return None
    if bool_value is not None:
        return name, bool_value
    if int_value is not None:
        return name, int_value
    if long_value is not None:
        return name, long_value
    if string_value is not None:
        return name, string_value
    return None


def _assign_metric_path(root: dict[str, Any], metric_name: str, value: Any) -> None:
    parts = [part for part in metric_name.replace(".", "/").split("/") if part]
    if not parts:
        return
    current = root
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _parse_topic(mqtt_topic: str) -> tuple[str, str, str, str | None] | None:
    parts = mqtt_topic.split("/")
    if len(parts) not in (4, 5):
        return None
    if parts[0] != SPARKPLUG_NAMESPACE:
        return None
    if any(part == "" for part in parts):
        return None

    _, group_id, message_type, edge_node_id, *device_parts = parts
    device_id = device_parts[0] if device_parts else None
    if device_id is None:
        if message_type not in NODE_MESSAGE_TYPES:
            return None
    else:
        if message_type not in DEVICE_MESSAGE_TYPES:
            return None
    return group_id, message_type, edge_node_id, device_id


def decode_sparkplug_payload(payload_base64: str, mqtt_topic: str) -> SparkplugMessage | None:
    topic_parts = _parse_topic(mqtt_topic)
    if topic_parts is None:
        return None

    try:
        payload = base64.b64decode(payload_base64, validate=True)
    except (binascii.Error, ValueError):
        return None

    group_id, message_type, edge_node_id, device_id = topic_parts
    offset = 0
    sparkplug_timestamp: int | None = None
    seq: int | None = None
    metrics: dict[str, Any] = {}
    try:
        while offset < len(payload):
            field_number, wire_type, offset = _read_key(payload, offset)
            if field_number == 1 and wire_type == 0:
                sparkplug_timestamp, offset = _read_varint(payload, offset)
                continue
            if field_number == 2 and wire_type == 2:
                metric_bytes, offset = _read_length_delimited(payload, offset)
                decoded_metric = _decode_metric(metric_bytes)
                if decoded_metric is not None:
                    metric_name, metric_value = decoded_metric
                    _assign_metric_path(metrics, metric_name, metric_value)
                continue
            if field_number == 3 and wire_type == 0:
                seq, offset = _read_varint(payload, offset)
                continue
            offset = _skip_field(payload, offset, wire_type)
    except ValueError:
        return None

    return SparkplugMessage(
        group_id=group_id,
        message_type=message_type,
        edge_node_id=edge_node_id,
        device_id=device_id,
        seq=seq,
        sparkplug_timestamp=sparkplug_timestamp,
        metrics=metrics,
    )


def _build_reported_payload(
    message: SparkplugMessage,
    observed_at: int,
    *,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    topic: dict[str, Any] = {
        "namespace": SPARKPLUG_NAMESPACE,
        "groupId": message.group_id,
        "messageType": message.message_type,
        "edgeNodeId": message.edge_node_id,
    }
    if message.device_id is not None:
        topic["deviceId"] = message.device_id

    payload: dict[str, Any] = {
        "timestamp": message.sparkplug_timestamp,
        "seq": message.seq,
        "metrics": metrics,
    }

    return {
        "topic": topic,
        "payload": payload,
        "projection": {
            "observedAt": observed_at,
        },
    }


@lru_cache(maxsize=1)
def _region_name() -> str:
    session = boto3.session.Session()
    return session.region_name or "eu-central-1"


@lru_cache(maxsize=1)
def _iot_data_client() -> Any:
    iot = boto3.client("iot", region_name=_region_name())
    endpoint = iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
    return boto3.client(
        "iot-data",
        region_name=_region_name(),
        endpoint_url=f"https://{endpoint}",
    )


@lru_cache(maxsize=1)
def _iot_client() -> Any:
    return boto3.client("iot", region_name=_region_name())


def _resolve_thing_name(message: SparkplugMessage) -> str:
    if message.device_id is not None:
        return message.device_id

    response = _iot_client().search_index(
        indexName=THING_INDEX_NAME,
        queryString=(
            f"thingTypeName:rig AND attributes.name:{message.edge_node_id}"
            f" AND attributes.town:{message.group_id}"
        ),
        maxResults=10,
    )
    matches = [
        thing.get("thingName")
        for thing in response.get("things", [])
        if isinstance(thing, dict) and isinstance(thing.get("thingName"), str)
    ]
    unique_matches = sorted(set(matches))
    if len(unique_matches) != 1:
        raise RuntimeError(
            f"Expected exactly one rig thing for group={message.group_id!r} edge={message.edge_node_id!r}, "
            f"got {unique_matches!r}"
        )
    return unique_matches[0]


def _update_named_shadow(thing_name: str, payload: dict[str, Any]) -> None:
    _iot_data_client().update_thing_shadow(
        thingName=thing_name,
        shadowName="sparkplug",
        payload=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    )


def _replace_metrics(thing_name: str, reported_payload: dict[str, Any]) -> None:
    _update_named_shadow(
        thing_name,
        {
            "state": {
                "reported": {
                    "payload": {
                        "metrics": None,
                    }
                }
            }
        },
    )
    _update_named_shadow(thing_name, {"state": {"reported": reported_payload}})


def _merge_metrics(thing_name: str, reported_payload: dict[str, Any]) -> None:
    _update_named_shadow(thing_name, {"state": {"reported": reported_payload}})


def project_sparkplug_message(message: SparkplugMessage, observed_at: int) -> str:
    thing_name = _resolve_thing_name(message)
    reported_payload = _build_reported_payload(
        message,
        observed_at,
        metrics=message.metrics,
    )

    if (
        message.message_type in REPLACE_METRICS_MESSAGE_TYPES
        or message.message_type in CLEAR_METRICS_MESSAGE_TYPES
    ):
        _replace_metrics(thing_name, reported_payload)
    elif message.message_type in MERGE_METRICS_MESSAGE_TYPES:
        _merge_metrics(thing_name, reported_payload)
    else:
        return "ignored"
    return thing_name


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    mqtt_topic = event.get("mqttTopic")
    payload_base64 = event.get("payloadBase64")
    observed_at = event.get("observedAt")
    if not isinstance(mqtt_topic, str) or not isinstance(payload_base64, str):
        LOGGER.warning("Ignoring malformed witness event: %s", event)
        return {"status": "ignored", "reason": "malformed-event"}
    if isinstance(observed_at, bool) or not isinstance(observed_at, int):
        observed_at = 0

    message = decode_sparkplug_payload(payload_base64, mqtt_topic)
    if message is None:
        return {"status": "ignored", "reason": "unsupported-topic"}

    thing_name = project_sparkplug_message(message, observed_at)
    return {"status": "ok", "thingName": thing_name}
