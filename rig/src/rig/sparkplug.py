from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum

SPARKPLUG_NAMESPACE = "spBv1.0"


class DataType(IntEnum):
    UNKNOWN = 0
    INT8 = 1
    INT16 = 2
    INT32 = 3
    INT64 = 4
    UINT8 = 5
    UINT16 = 6
    UINT32 = 7
    UINT64 = 8
    FLOAT = 9
    DOUBLE = 10
    BOOLEAN = 11
    STRING = 12
    DATETIME = 13
    TEXT = 14
    UUID = 15
    DATASET = 16
    BYTES = 17
    FILE = 18
    TEMPLATE = 19
    PROPERTY_SET = 20
    PROPERTY_SET_LIST = 21
    INT8_ARRAY = 22
    INT16_ARRAY = 23
    INT32_ARRAY = 24
    INT64_ARRAY = 25
    UINT8_ARRAY = 26
    UINT16_ARRAY = 27
    UINT32_ARRAY = 28
    UINT64_ARRAY = 29
    FLOAT_ARRAY = 30
    DOUBLE_ARRAY = 31
    BOOLEAN_ARRAY = 32
    STRING_ARRAY = 33
    DATETIME_ARRAY = 34


@dataclass(slots=True, frozen=True)
class Metric:
    name: str
    datatype: DataType
    int_value: int | None = None
    long_value: int | None = None
    bool_value: bool | None = None
    string_value: str | None = None
    timestamp: int | None = None


@dataclass(slots=True, frozen=True)
class Payload:
    timestamp: int
    metrics: tuple[Metric, ...]
    seq: int | None = None


@dataclass(slots=True, frozen=True)
class DecodedCommand:
    metric_name: str
    value: int
    seq: int | None
    timestamp: int | None


def utc_timestamp_ms() -> int:
    return int(time.time() * 1000)


def build_node_topic(group_id: str, message_type: str, edge_node_id: str) -> str:
    return f"{SPARKPLUG_NAMESPACE}/{group_id}/{message_type}/{edge_node_id}"


def build_device_topic(
    group_id: str,
    message_type: str,
    edge_node_id: str,
    device_id: str,
) -> str:
    return f"{SPARKPLUG_NAMESPACE}/{group_id}/{message_type}/{edge_node_id}/{device_id}"


def encode_payload(payload: Payload) -> bytes:
    chunks = bytearray()
    _append_varint_field(chunks, 1, payload.timestamp)
    for metric in payload.metrics:
        _append_bytes_field(chunks, 2, encode_metric(metric))
    if payload.seq is not None:
        _append_varint_field(chunks, 3, payload.seq)
    return bytes(chunks)


def encode_metric(metric: Metric) -> bytes:
    chunks = bytearray()
    _append_string_field(chunks, 1, metric.name)
    if metric.timestamp is not None:
        _append_varint_field(chunks, 3, metric.timestamp)
    _append_varint_field(chunks, 4, int(metric.datatype))
    if metric.int_value is not None:
        _append_varint_field(chunks, 10, metric.int_value)
    elif metric.long_value is not None:
        _append_varint_field(chunks, 11, metric.long_value)
    elif metric.bool_value is not None:
        _append_varint_field(chunks, 12, 1 if metric.bool_value else 0)
    elif metric.string_value is not None:
        _append_string_field(chunks, 13, metric.string_value)
    else:
        raise ValueError(f"metric {metric.name!r} is missing a value")
    return bytes(chunks)


def decode_payload(data: bytes) -> Payload:
    offset = 0
    timestamp: int | None = None
    seq: int | None = None
    metrics: list[Metric] = []
    while offset < len(data):
        field_number, wire_type, offset = _read_key(data, offset)
        if field_number == 1 and wire_type == 0:
            timestamp, offset = _read_varint(data, offset)
            continue
        if field_number == 2 and wire_type == 2:
            metric_bytes, offset = _read_length_delimited(data, offset)
            metrics.append(decode_metric(metric_bytes))
            continue
        if field_number == 3 and wire_type == 0:
            seq, offset = _read_varint(data, offset)
            continue
        offset = _skip_field(data, offset, wire_type)
    return Payload(timestamp=timestamp or 0, metrics=tuple(metrics), seq=seq)


def decode_metric(data: bytes) -> Metric:
    offset = 0
    name = ""
    datatype = DataType.UNKNOWN
    timestamp: int | None = None
    int_value: int | None = None
    long_value: int | None = None
    bool_value: bool | None = None
    string_value: str | None = None
    while offset < len(data):
        field_number, wire_type, offset = _read_key(data, offset)
        if field_number == 1 and wire_type == 2:
            raw, offset = _read_length_delimited(data, offset)
            name = raw.decode("utf-8")
            continue
        if field_number == 3 and wire_type == 0:
            timestamp, offset = _read_varint(data, offset)
            continue
        if field_number == 4 and wire_type == 0:
            raw_datatype, offset = _read_varint(data, offset)
            datatype = DataType(raw_datatype)
            continue
        if field_number == 10 and wire_type == 0:
            int_value, offset = _read_varint(data, offset)
            continue
        if field_number == 11 and wire_type == 0:
            long_value, offset = _read_varint(data, offset)
            continue
        if field_number == 12 and wire_type == 0:
            raw_bool, offset = _read_varint(data, offset)
            bool_value = raw_bool != 0
            continue
        if field_number == 13 and wire_type == 2:
            raw, offset = _read_length_delimited(data, offset)
            string_value = raw.decode("utf-8")
            continue
        offset = _skip_field(data, offset, wire_type)
    return Metric(
        name=name,
        datatype=datatype,
        int_value=int_value,
        long_value=long_value,
        bool_value=bool_value,
        string_value=string_value,
        timestamp=timestamp,
    )


def decode_redcon_command(data: bytes) -> DecodedCommand | None:
    payload = decode_payload(data)
    for metric in payload.metrics:
        if metric.name != "redcon":
            continue
        value = metric.int_value if metric.int_value is not None else metric.long_value
        if value is None or not 1 <= value <= 4:
            return None
        return DecodedCommand(
            metric_name=metric.name,
            value=value,
            seq=payload.seq,
            timestamp=payload.timestamp,
        )
    return None


def build_redcon_payload(*, redcon: int, seq: int, timestamp: int | None = None) -> bytes:
    if not 1 <= redcon <= 4:
        raise ValueError(f"redcon must be between 1 and 4, got {redcon}")
    payload = Payload(
        timestamp=timestamp if timestamp is not None else utc_timestamp_ms(),
        metrics=(Metric(name="redcon", datatype=DataType.INT32, int_value=redcon),),
        seq=seq,
    )
    return encode_payload(payload)


def build_device_report_payload(
    *,
    redcon: int,
    battery_mv: int,
    seq: int,
    extra_metrics: tuple[Metric, ...] = (),
    timestamp: int | None = None,
) -> bytes:
    if battery_mv < 0:
        raise ValueError("battery_mv must not be negative")
    payload = Payload(
        timestamp=timestamp if timestamp is not None else utc_timestamp_ms(),
        metrics=(
            Metric(name="redcon", datatype=DataType.INT32, int_value=redcon),
            Metric(name="batteryMv", datatype=DataType.INT32, int_value=battery_mv),
            *extra_metrics,
        ),
        seq=seq,
    )
    return encode_payload(payload)


def build_node_birth_payload(
    *,
    redcon: int,
    bdseq: int,
    seq: int,
    timestamp: int | None = None,
) -> bytes:
    if bdseq < 0:
        raise ValueError("bdseq must not be negative")
    payload = Payload(
        timestamp=timestamp if timestamp is not None else utc_timestamp_ms(),
        metrics=(
            Metric(name="bdSeq", datatype=DataType.UINT64, long_value=bdseq),
            Metric(name="redcon", datatype=DataType.INT32, int_value=redcon),
        ),
        seq=seq,
    )
    return encode_payload(payload)


def build_node_death_payload(
    *,
    bdseq: int,
    redcon: int = 4,
    timestamp: int | None = None,
) -> bytes:
    if bdseq < 0:
        raise ValueError("bdseq must not be negative")
    if not 1 <= redcon <= 4:
        raise ValueError(f"redcon must be between 1 and 4, got {redcon}")
    payload = Payload(
        timestamp=timestamp if timestamp is not None else utc_timestamp_ms(),
        metrics=(
            Metric(name="bdSeq", datatype=DataType.UINT64, long_value=bdseq),
            Metric(name="redcon", datatype=DataType.INT32, int_value=redcon),
        ),
    )
    return encode_payload(payload)


def _append_key(chunks: bytearray, field_number: int, wire_type: int) -> None:
    _append_varint(chunks, (field_number << 3) | wire_type)


def _append_varint_field(chunks: bytearray, field_number: int, value: int) -> None:
    _append_key(chunks, field_number, 0)
    _append_varint(chunks, value)


def _append_string_field(chunks: bytearray, field_number: int, value: str) -> None:
    _append_bytes_field(chunks, field_number, value.encode("utf-8"))


def _append_bytes_field(chunks: bytearray, field_number: int, value: bytes) -> None:
    _append_key(chunks, field_number, 2)
    _append_varint(chunks, len(value))
    chunks.extend(value)


def _append_varint(chunks: bytearray, value: int) -> None:
    if value < 0:
        raise ValueError(f"Sparkplug varint values must be non-negative, got {value}")
    remaining = value
    while True:
        next_byte = remaining & 0x7F
        remaining >>= 7
        if remaining:
            chunks.append(next_byte | 0x80)
            continue
        chunks.append(next_byte)
        return


def _read_key(data: bytes, offset: int) -> tuple[int, int, int]:
    key, next_offset = _read_varint(data, offset)
    return key >> 3, key & 0x07, next_offset


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    index = offset
    while True:
        if index >= len(data):
            raise ValueError("unexpected end of buffer while reading varint")
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, index
        shift += 7
        if shift > 63:
            raise ValueError("varint is too large")


def _read_length_delimited(data: bytes, offset: int) -> tuple[bytes, int]:
    length, next_offset = _read_varint(data, offset)
    end = next_offset + length
    if end > len(data):
        raise ValueError("unexpected end of buffer while reading bytes field")
    return data[next_offset:end], end


def _skip_field(data: bytes, offset: int, wire_type: int) -> int:
    if wire_type == 0:
        _, next_offset = _read_varint(data, offset)
        return next_offset
    if wire_type == 1:
        next_offset = offset + 8
        if next_offset > len(data):
            raise ValueError("unexpected end of buffer while skipping fixed64 field")
        return next_offset
    if wire_type == 2:
        _, next_offset = _read_length_delimited(data, offset)
        return next_offset
    if wire_type == 5:
        next_offset = offset + 4
        if next_offset > len(data):
            raise ValueError("unexpected end of buffer while skipping fixed32 field")
        return next_offset
    raise ValueError(f"unsupported wire type {wire_type}")
