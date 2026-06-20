from __future__ import annotations

import importlib.util
import binascii
import struct
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "thread_factory.py"
spec = importlib.util.spec_from_file_location("thread_factory", SCRIPT)
thread_factory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = thread_factory
spec.loader.exec_module(thread_factory)


class ThreadFactoryTests(unittest.TestCase):
    def test_build_factory_data_contains_txt1_record_and_crc(self) -> None:
        dataset = bytes.fromhex("0e080000000000010000000300001235")
        payload = thread_factory.build_factory_data("power-si-001", dataset, 5683)

        magic, version, name_len, dataset_len, port = struct.unpack("<4sBBHH", payload[:10])
        self.assertEqual(magic, b"TXT1")
        self.assertEqual(version, 1)
        self.assertEqual(name_len, len("power-si-001"))
        self.assertEqual(dataset_len, len(dataset))
        self.assertEqual(port, 5683)
        self.assertEqual(payload[10 : 10 + name_len], b"power-si-001")
        self.assertEqual(payload[10 + name_len : -4], dataset)
        self.assertEqual(struct.unpack("<I", payload[-4:])[0], binascii.crc32(payload[:-4]))

    def test_rejects_invalid_thing_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            thread_factory.build_factory_data("", b"\x01")
        with self.assertRaisesRegex(ValueError, "ASCII"):
            thread_factory.build_factory_data("power-si-\N{SNOWMAN}", b"\x01")
        with self.assertRaisesRegex(ValueError, "printable non-space"):
            thread_factory.build_factory_data("power si", b"\x01")

    def test_rejects_malformed_dataset_tlvs(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole bytes"):
            thread_factory.parse_dataset_tlvs_hex("abc")
        with self.assertRaisesRegex(ValueError, "must be hex"):
            thread_factory.parse_dataset_tlvs_hex("zz")
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            thread_factory.parse_dataset_tlvs_hex("")

    def test_rejects_oversized_dataset_tlvs(self) -> None:
        with self.assertRaisesRegex(ValueError, "too large"):
            thread_factory.build_factory_data("power-si-001", bytes(255))

    def test_rejects_record_larger_than_factory_partition(self) -> None:
        original_size = thread_factory.FACTORY_PARTITION_SIZE
        try:
            thread_factory.FACTORY_PARTITION_SIZE = 12
            with self.assertRaisesRegex(ValueError, "factory record is too large"):
                thread_factory.build_factory_data("power-si-001", b"\x01\x02")
        finally:
            thread_factory.FACTORY_PARTITION_SIZE = original_size

    def test_write_hex_uses_mg24_factory_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "factory.hex"
            thread_factory.write_hex("power-si-001", b"\x01\x02", output)
            text = output.read_text(encoding="ascii")

        self.assertIn(":020000040017E3", text)
        self.assertIn(":00000001FF", text)


if __name__ == "__main__":
    unittest.main()
