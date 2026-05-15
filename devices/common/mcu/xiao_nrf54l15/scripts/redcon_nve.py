#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import struct
import sys
from pathlib import Path


DEFAULT_FACTORY_DATA_ADDRESS = 0x000F0000
FACTORY_DATA_MAGIC = b"TXR1"
FACTORY_DATA_VERSION = 1
FACTORY_DEVICE_NAME_SIZE = 26
FACTORY_DATA_STRUCT = struct.Struct("<4sBB26sI")


def parse_address(value: str) -> int:
    try:
        address = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid address: {value!r}") from exc
    if address < 0 or address > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(f"address out of range: {value!r}")
    return address


def validate_device_name(value: str) -> str:
    device_name = value.strip()
    if not device_name:
        raise ValueError("device name must not be empty")
    try:
        encoded = device_name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("device name must be ASCII") from exc
    if len(encoded) > FACTORY_DEVICE_NAME_SIZE:
        raise ValueError(
            f"device name is too long ({len(encoded)} > {FACTORY_DEVICE_NAME_SIZE} bytes): "
            f"{device_name!r}"
        )
    if any(byte < 0x21 or byte > 0x7E for byte in encoded):
        raise ValueError("device name may contain only printable non-space ASCII")
    return device_name


def build_factory_data(device_name: str) -> bytes:
    normalized = validate_device_name(device_name)
    encoded = normalized.encode("ascii")
    name_field = encoded.ljust(FACTORY_DEVICE_NAME_SIZE, b"\0")
    without_crc = FACTORY_DATA_STRUCT.pack(
        FACTORY_DATA_MAGIC,
        FACTORY_DATA_VERSION,
        len(encoded),
        name_field,
        0,
    )[:-4]
    crc = binascii.crc32(without_crc) & 0xFFFFFFFF
    return without_crc + struct.pack("<I", crc)


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


def write_hex(device_name: str, output: Path, address: int) -> None:
    payload = build_factory_data(device_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_intel_hex(address, payload), encoding="ascii")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--address",
        type=parse_address,
        default=DEFAULT_FACTORY_DATA_ADDRESS,
        help=f"factory/NVE flash address, default 0x{DEFAULT_FACTORY_DATA_ADDRESS:08x}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build REDCON factory/NVE data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser("write-hex", help="write a REDCON factory/NVE HEX file")
    write_parser.add_argument("device_name", help="BLE device name to store")
    write_parser.add_argument("--output", type=Path, required=True, help="output Intel HEX path")
    add_common_args(write_parser)

    validate_parser = subparsers.add_parser("validate", help="validate a BLE device name")
    validate_parser.add_argument("device_name", help="BLE device name to validate")

    args = parser.parse_args(argv)
    try:
        if args.command == "write-hex":
            device_name = validate_device_name(args.device_name)
            write_hex(device_name, args.output, args.address)
            print(f"wrote {args.output}")
            print(f"address 0x{args.address:08x}")
            print(f"deviceName {device_name}")
        elif args.command == "validate":
            print(validate_device_name(args.device_name))
        else:
            parser.error(f"unsupported command: {args.command}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
