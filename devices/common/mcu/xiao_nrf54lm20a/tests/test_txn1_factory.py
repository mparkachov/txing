from __future__ import annotations

import binascii
import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "thread_factory.py"
LM20A_OVERLAY = (
    Path(__file__).resolve().parents[1]
    / "boards"
    / "xiao_nrf54lm20a_nrf54lm20a_cpuapp.overlay"
)
spec = importlib.util.spec_from_file_location("power_nrf_thread_factory", SCRIPT)
thread_factory = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = thread_factory
spec.loader.exec_module(thread_factory)


class PowerNrfTxn1FactoryTests(unittest.TestCase):
    def test_build_and_parse_factory_data_contains_txn1_record_and_crc(self) -> None:
        dataset = bytes.fromhex("0e080000000000010000000300001235")
        payload = thread_factory.build_factory_data("power-nrf-001", dataset, 5683)

        magic, version, name_len, dataset_len, port = struct.unpack("<4sBBHH", payload[:10])
        self.assertEqual(magic, b"TXN1")
        self.assertEqual(version, 1)
        self.assertEqual(name_len, len("power-nrf-001"))
        self.assertEqual(dataset_len, len(dataset))
        self.assertEqual(port, 5683)
        self.assertEqual(struct.unpack("<I", payload[-4:])[0], binascii.crc32(payload[:-4]))
        self.assertEqual(
            thread_factory.parse_factory_data(payload),
            thread_factory.FactoryRecord("power-nrf-001", dataset, 5683),
        )

    def test_rejects_malformed_magic_version_length_and_crc(self) -> None:
        payload = thread_factory.build_factory_data("power-nrf-001", b"\x01\x02")

        with self.assertRaisesRegex(ValueError, "truncated"):
            thread_factory.parse_factory_data(payload[:5])
        with self.assertRaisesRegex(ValueError, "magic"):
            thread_factory.parse_factory_data(b"BAD1" + payload[4:])
        unsupported_version = bytearray(payload)
        unsupported_version[4] = 2
        with self.assertRaisesRegex(ValueError, "version"):
            thread_factory.parse_factory_data(bytes(unsupported_version))
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            thread_factory.parse_factory_data(payload + b"\x00")
        bad_crc = bytearray(payload)
        bad_crc[-1] ^= 0x01
        with self.assertRaisesRegex(ValueError, "CRC32"):
            thread_factory.parse_factory_data(bytes(bad_crc))

    def test_rejects_invalid_or_oversize_factory_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            thread_factory.build_factory_data("", b"\x01")
        with self.assertRaisesRegex(ValueError, "ASCII"):
            thread_factory.build_factory_data("power-nrf-\N{SNOWMAN}", b"\x01")
        with self.assertRaisesRegex(ValueError, "too large"):
            thread_factory.build_factory_data("power-nrf-001", bytes(255))
        with self.assertRaisesRegex(ValueError, "out of range"):
            thread_factory.build_factory_data("power-nrf-001", b"\x01", 0)

    def test_write_hex_uses_nrf54lm20a_factory_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "factory.hex"
            thread_factory.write_hex("power-nrf-001", b"\x01\x02", output)
            text = output.read_text(encoding="ascii")

        self.assertIn(":02000004001FDB", text)
        self.assertIn(":10400000", text)
        self.assertIn(":00000001FF", text)

    def test_rejects_factory_writes_outside_the_8k_partition(self) -> None:
        payload = thread_factory.build_factory_data("power-nrf-001", b"\x01\x02")
        with self.assertRaisesRegex(ValueError, "precedes"):
            thread_factory.validate_factory_write(
                thread_factory.FACTORY_PARTITION_ADDRESS - 1,
                len(payload),
            )
        with self.assertRaisesRegex(ValueError, "overlap"):
            thread_factory.validate_factory_write(
                thread_factory.SETTINGS_PARTITION_ADDRESS,
                len(payload),
            )
        thread_factory.validate_factory_write(
            thread_factory.SETTINGS_PARTITION_ADDRESS - len(payload),
            len(payload),
        )

    def test_shared_overlay_splits_stock_storage_into_factory_and_settings(self) -> None:
        overlay = LM20A_OVERLAY.read_text(encoding="ascii")

        self.assertIn("/delete-node/ partition@1f4000;", overlay)
        self.assertIn("txing_factory_partition: partition@1f4000", overlay)
        self.assertIn("reg = <0x001f4000 DT_SIZE_K(8)>;", overlay)
        self.assertIn("read-only;", overlay)
        self.assertIn("txing_ot_settings_partition: partition@1f6000", overlay)
        self.assertIn("reg = <0x001f6000 DT_SIZE_K(28)>;", overlay)
        self.assertIn("zephyr,settings-partition = &txing_ot_settings_partition;", overlay)


if __name__ == "__main__":
    unittest.main()
