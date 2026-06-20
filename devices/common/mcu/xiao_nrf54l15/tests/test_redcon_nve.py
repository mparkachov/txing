from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "redcon_nve.py"
spec = importlib.util.spec_from_file_location("redcon_nve", SCRIPT)
redcon_nve = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = redcon_nve
spec.loader.exec_module(redcon_nve)


class RedconNveTests(unittest.TestCase):
    def test_build_factory_data_keeps_txr1_layout(self) -> None:
        payload = redcon_nve.build_factory_data("power-001")
        magic, version, name_len, name_field, _crc = struct.unpack("<4sBB26sI", payload)

        self.assertEqual(magic, b"TXR1")
        self.assertEqual(version, 1)
        self.assertEqual(name_len, len("power-001"))
        self.assertEqual(name_field[:name_len], b"power-001")
        self.assertEqual(len(payload), redcon_nve.FACTORY_DATA_STRUCT.size)

    def test_existing_name_validation_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            redcon_nve.validate_device_name("")
        with self.assertRaisesRegex(ValueError, "ASCII"):
            redcon_nve.validate_device_name("power-\N{SNOWMAN}")
        with self.assertRaisesRegex(ValueError, "too long"):
            redcon_nve.validate_device_name("x" * 27)


if __name__ == "__main__":
    unittest.main()
