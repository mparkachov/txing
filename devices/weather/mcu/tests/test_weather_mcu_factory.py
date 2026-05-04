from __future__ import annotations

import binascii
import importlib.util
import struct
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "weather_mcu.py"
SPEC = importlib.util.spec_from_file_location("weather_mcu", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
weather_mcu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(weather_mcu)


class WeatherMcuFactoryDataTests(unittest.TestCase):
    def test_factory_data_contains_thing_name_and_crc(self) -> None:
        payload = weather_mcu.build_factory_data("weather-q8zbgb")

        self.assertEqual(len(payload), weather_mcu.FACTORY_DATA_STRUCT.size)
        magic, version, name_len, name_field, crc = weather_mcu.FACTORY_DATA_STRUCT.unpack(payload)
        self.assertEqual(magic, weather_mcu.FACTORY_DATA_MAGIC)
        self.assertEqual(version, weather_mcu.FACTORY_DATA_VERSION)
        self.assertEqual(name_len, len("weather-q8zbgb"))
        self.assertEqual(name_field[:name_len], b"weather-q8zbgb")
        self.assertEqual(name_field[name_len:], b"\0" * (weather_mcu.FACTORY_THING_NAME_SIZE - name_len))
        self.assertEqual(crc, binascii.crc32(payload[:-4]) & 0xFFFFFFFF)

    def test_rejects_too_long_or_non_ascii_thing_name(self) -> None:
        with self.assertRaises(SystemExit):
            weather_mcu.validate_thing_name("x" * (weather_mcu.FACTORY_THING_NAME_SIZE + 1))
        with self.assertRaises(SystemExit):
            weather_mcu.validate_thing_name("weather-é")
        with self.assertRaises(SystemExit):
            weather_mcu.validate_thing_name("weather one")

    def test_factory_data_layout_matches_firmware_reader(self) -> None:
        self.assertEqual(weather_mcu.FACTORY_DATA_STRUCT.format, "<4sBB26sI")
        self.assertEqual(weather_mcu.FACTORY_DATA_STRUCT.size, 36)
        self.assertEqual(struct.unpack("<I", weather_mcu.FACTORY_DATA_MAGIC)[0], 0x31575854)


if __name__ == "__main__":
    unittest.main()
