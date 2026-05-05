from __future__ import annotations

import struct
from dataclasses import dataclass


WEATHER_SERVICE_UUID = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_COMMAND_UUID = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_STATE_UUID = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100"
WEATHER_MEASUREMENT_UUID = "f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100"

PROTOCOL_VERSION = 1
REDCON_ACTIVE = 3
REDCON_IDLE = 4
STATE_FLAG_ACTIVE = 0x01
STATE_FLAG_BME280_VALID = 0x02

COMMAND_STRUCT = struct.Struct("<BB")
STATE_STRUCT = struct.Struct("<BBBH")
MEASUREMENT_STRUCT = struct.Struct("<BiIHH")


@dataclass(slots=True, frozen=True)
class WeatherState:
    redcon: int
    active: bool
    bme280_valid: bool
    battery_mv: int | None


@dataclass(slots=True, frozen=True)
class WeatherMeasurement:
    temperature_c: float
    pressure_kpa: float
    humidity_percent: float
    battery_mv: int | None


def normalize_redcon(redcon: int) -> int:
    if redcon in (1, 2):
        return REDCON_ACTIVE
    if redcon in (REDCON_ACTIVE, REDCON_IDLE):
        return redcon
    raise ValueError(f"unsupported weather REDCON: {redcon}")


def encode_command(redcon: int) -> bytes:
    return COMMAND_STRUCT.pack(PROTOCOL_VERSION, normalize_redcon(redcon))


def parse_state(data: bytes | bytearray | memoryview) -> WeatherState:
    payload = bytes(data)
    if len(payload) < STATE_STRUCT.size:
        raise ValueError("weather state payload is too short")
    version, redcon, flags, battery_mv = STATE_STRUCT.unpack_from(payload)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported weather state version: {version}")
    redcon = normalize_redcon(redcon)
    return WeatherState(
        redcon=redcon,
        active=bool(flags & STATE_FLAG_ACTIVE),
        bme280_valid=bool(flags & STATE_FLAG_BME280_VALID),
        battery_mv=battery_mv or None,
    )


def parse_measurement(data: bytes | bytearray | memoryview) -> WeatherMeasurement:
    payload = bytes(data)
    if len(payload) < MEASUREMENT_STRUCT.size:
        raise ValueError("weather measurement payload is too short")
    version, temperature_centi, pressure_pa, humidity_centi, battery_mv = (
        MEASUREMENT_STRUCT.unpack_from(payload)
    )
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported weather measurement version: {version}")
    return WeatherMeasurement(
        temperature_c=temperature_centi / 100.0,
        pressure_kpa=pressure_pa / 1000.0,
        humidity_percent=humidity_centi / 100.0,
        battery_mv=battery_mv or None,
    )


def encode_state_for_test(
    *,
    redcon: int,
    active: bool | None = None,
    bme280_valid: bool = False,
    battery_mv: int = 0,
) -> bytes:
    normalized = normalize_redcon(redcon)
    flags = 0
    is_active = active if active is not None else normalized == REDCON_ACTIVE
    if is_active:
        flags |= STATE_FLAG_ACTIVE
    if bme280_valid:
        flags |= STATE_FLAG_BME280_VALID
    return STATE_STRUCT.pack(PROTOCOL_VERSION, normalized, flags, battery_mv)


def encode_measurement_for_test(
    *,
    temperature_c: float,
    pressure_kpa: float,
    humidity_percent: float,
    battery_mv: int = 0,
) -> bytes:
    return MEASUREMENT_STRUCT.pack(
        PROTOCOL_VERSION,
        int(round(temperature_c * 100)),
        int(round(pressure_kpa * 1000)),
        int(round(humidity_percent * 100)),
        battery_mv,
    )
