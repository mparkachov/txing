#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
from dataclasses import dataclass
import re
import struct
import sys
from pathlib import Path


STORAGE_REGION_ADDRESS = 0x001F4000
STORAGE_REGION_SIZE = 36 * 1024
FACTORY_PARTITION_ADDRESS = STORAGE_REGION_ADDRESS
FACTORY_PARTITION_SIZE = 8 * 1024
SETTINGS_PARTITION_ADDRESS = FACTORY_PARTITION_ADDRESS + FACTORY_PARTITION_SIZE
SETTINGS_PARTITION_SIZE = STORAGE_REGION_SIZE - FACTORY_PARTITION_SIZE
FACTORY_DATA_MAGIC = b"TXN1"
FACTORY_DATA_VERSION = 1
FACTORY_THING_NAME_SIZE = 64
THREAD_DATASET_TLVS_SIZE = 254
FACTORY_DATA_HEADER = struct.Struct("<4sBBHH")
FACTORY_DATA_CRC = struct.Struct("<I")
THING_NAME_RE = re.compile(r"^[!-~]+$")


@dataclass(frozen=True)
class FactoryRecord:
    thing_name: str
    dataset_tlvs: bytes
    coap_port: int


def parse_address(value: str) -> int:
    try:
        address = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid address: {value!r}") from exc
    if address < 0 or address > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(f"address out of range: {value!r}")
    return address


def validate_thing_name(value: str) -> str:
    thing_name = value.strip()
    if not thing_name:
        raise ValueError("Thing name must not be empty")
    try:
        encoded = thing_name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Thing name must be ASCII") from exc
    if len(encoded) > FACTORY_THING_NAME_SIZE:
        raise ValueError(
            f"Thing name is too long ({len(encoded)} > {FACTORY_THING_NAME_SIZE} bytes): "
            f"{thing_name!r}"
        )
    if not THING_NAME_RE.fullmatch(thing_name):
        raise ValueError("Thing name may contain only printable non-space ASCII")
    return thing_name


def validate_dataset_tlvs(dataset_tlvs: bytes) -> bytes:
    if not dataset_tlvs:
        raise ValueError("Thread Active Operational Dataset TLVs must not be empty")
    if len(dataset_tlvs) > THREAD_DATASET_TLVS_SIZE:
        raise ValueError(
            "Thread Active Operational Dataset TLVs are too large "
            f"({len(dataset_tlvs)} > {THREAD_DATASET_TLVS_SIZE} bytes)"
        )
    return dataset_tlvs


def parse_dataset_tlvs_hex(value: str) -> bytes:
    compact = "".join(value.split())
    if compact.startswith(("0x", "0X")):
        compact = compact[2:]
    if not compact:
        raise ValueError("Thread Active Operational Dataset TLVs must not be empty")
    if len(compact) % 2:
        raise ValueError("Thread Active Operational Dataset TLVs hex must contain whole bytes")
    if re.search(r"[^0-9a-fA-F]", compact):
        raise ValueError("Thread Active Operational Dataset TLVs must be hex")
    return validate_dataset_tlvs(bytes.fromhex(compact))


def read_dataset_tlvs(path: Path) -> bytes:
    if not path.exists():
        raise ValueError(f"Thread Active Operational Dataset TLVs file does not exist: {path}")
    return parse_dataset_tlvs_hex(path.read_text(encoding="ascii"))


def validate_port(value: int) -> int:
    if value < 1 or value > 0xFFFF:
        raise ValueError(f"CoAP port out of range: {value}")
    return value


def build_factory_data(thing_name: str, dataset_tlvs: bytes, port: int = 5683) -> bytes:
    normalized_name = validate_thing_name(thing_name)
    validated_dataset = validate_dataset_tlvs(dataset_tlvs)
    validated_port = validate_port(port)
    name_bytes = normalized_name.encode("ascii")
    without_crc = (
        FACTORY_DATA_HEADER.pack(
            FACTORY_DATA_MAGIC,
            FACTORY_DATA_VERSION,
            len(name_bytes),
            len(validated_dataset),
            validated_port,
        )
        + name_bytes
        + validated_dataset
    )
    payload = without_crc + FACTORY_DATA_CRC.pack(binascii.crc32(without_crc) & 0xFFFFFFFF)
    if len(payload) > FACTORY_PARTITION_SIZE:
        raise ValueError(
            f"factory record is too large ({len(payload)} > {FACTORY_PARTITION_SIZE} bytes)"
        )
    return payload


def parse_factory_data(payload: bytes) -> FactoryRecord:
    minimum_size = FACTORY_DATA_HEADER.size + FACTORY_DATA_CRC.size
    if len(payload) < minimum_size:
        raise ValueError("TXN1 factory record is truncated")
    magic, version, name_len, dataset_len, port = FACTORY_DATA_HEADER.unpack_from(payload)
    if magic != FACTORY_DATA_MAGIC:
        raise ValueError(f"unexpected factory record magic: {magic!r}")
    if version != FACTORY_DATA_VERSION:
        raise ValueError(f"unsupported TXN1 factory record version: {version}")
    record_size = minimum_size + name_len + dataset_len
    if len(payload) != record_size:
        raise ValueError(
            f"TXN1 factory record length mismatch ({len(payload)} != {record_size})"
        )
    stored_crc = FACTORY_DATA_CRC.unpack_from(payload, record_size - FACTORY_DATA_CRC.size)[0]
    computed_crc = binascii.crc32(payload[:-FACTORY_DATA_CRC.size]) & 0xFFFFFFFF
    if stored_crc != computed_crc:
        raise ValueError("TXN1 factory record CRC32 mismatch")
    name_start = FACTORY_DATA_HEADER.size
    dataset_start = name_start + name_len
    try:
        thing_name = payload[name_start:dataset_start].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("TXN1 Thing name must be ASCII") from exc
    return FactoryRecord(
        thing_name=validate_thing_name(thing_name),
        dataset_tlvs=validate_dataset_tlvs(payload[dataset_start:-FACTORY_DATA_CRC.size]),
        coap_port=validate_port(port),
    )


def validate_factory_write(address: int, payload_size: int) -> None:
    if address < FACTORY_PARTITION_ADDRESS:
        raise ValueError(
            f"factory address 0x{address:08x} precedes factory partition "
            f"0x{FACTORY_PARTITION_ADDRESS:08x}"
        )
    partition_end = FACTORY_PARTITION_ADDRESS + FACTORY_PARTITION_SIZE
    if payload_size > partition_end - address:
        raise ValueError(
            "factory record exceeds the 8 KiB factory partition and would overlap "
            f"OpenThread settings at 0x{SETTINGS_PARTITION_ADDRESS:08x}"
        )


def intel_hex_checksum(body: bytes) -> int:
    return (-sum(body)) & 0xFF


def intel_hex_record(address: int, record_type: int, data: bytes = b"") -> str:
    if address < 0 or address > 0xFFFF:
        raise ValueError(f"Intel HEX record address out of range: 0x{address:x}")
    if len(data) > 0xFF:
        raise ValueError("Intel HEX record is too large")
    body = bytes([len(data), address >> 8, address & 0xFF, record_type]) + data
    return f":{body.hex().upper()}{intel_hex_checksum(body):02X}"


def build_intel_hex(address: int, data: bytes) -> str:
    lines: list[str] = []
    offset = 0
    current_high = None
    while offset < len(data):
        absolute = address + offset
        high = absolute >> 16
        low = absolute & 0xFFFF
        if high != current_high:
            lines.append(intel_hex_record(0, 0x04, high.to_bytes(2, "big")))
            current_high = high
        chunk_size = min(16, len(data) - offset, 0x10000 - low)
        lines.append(intel_hex_record(low, 0x00, data[offset : offset + chunk_size]))
        offset += chunk_size
    lines.append(intel_hex_record(0, 0x01))
    return "\n".join(lines) + "\n"


def write_hex(
    thing_name: str,
    dataset_tlvs: bytes,
    output: Path,
    *,
    address: int = FACTORY_PARTITION_ADDRESS,
    port: int = 5683,
) -> None:
    payload = build_factory_data(thing_name, dataset_tlvs, port)
    validate_factory_write(address, len(payload))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_intel_hex(address, payload), encoding="ascii")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset-tlvs",
        type=Path,
        required=True,
        help="path containing Thread Active Operational Dataset TLVs as hex",
    )
    parser.add_argument("--port", type=int, default=5683, help="CoAP port to store, default 5683")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build nRF54LM20A Thread TXN1 factory data.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    write_parser = subparsers.add_parser("write-hex", help="write a TXN1 factory HEX file")
    write_parser.add_argument("thing_name", help="Thing name to store")
    write_parser.add_argument("--output", type=Path, required=True, help="output Intel HEX path")
    write_parser.add_argument(
        "--address",
        type=parse_address,
        default=FACTORY_PARTITION_ADDRESS,
        help=f"factory RRAM address, default 0x{FACTORY_PARTITION_ADDRESS:08x}",
    )
    add_common_args(write_parser)
    validate_parser = subparsers.add_parser("validate", help="validate TXN1 factory inputs")
    validate_parser.add_argument("thing_name", help="Thing name to validate")
    add_common_args(validate_parser)
    args = parser.parse_args(argv)
    try:
        dataset = read_dataset_tlvs(args.dataset_tlvs)
        port = validate_port(args.port)
        if args.command == "write-hex":
            thing_name = validate_thing_name(args.thing_name)
            write_hex(thing_name, dataset, args.output, address=args.address, port=port)
            print(f"wrote {args.output}")
            print(f"address 0x{args.address:08x}")
            print(f"thingName {thing_name}")
            print(f"datasetTlvsBytes {len(dataset)}")
            print(f"coapPort {port}")
        elif args.command == "validate":
            print(validate_thing_name(args.thing_name))
            print(f"datasetTlvsBytes {len(dataset)}")
            print(f"coapPort {port}")
        else:
            parser.error(f"unsupported command: {args.command}")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
