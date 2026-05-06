from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_stability_matrix.py"
SPEC = importlib.util.spec_from_file_location("weather_ble_debug_stability_matrix", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
matrix = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = matrix
SPEC.loader.exec_module(matrix)


class WeatherBleDebugStabilityMatrixTests(unittest.TestCase):
    def test_openocd_diagnostics_extracts_flash_failure(self) -> None:
        path = self._write_log(
            "\n".join(
                (
                    "flash attempt 1/4 label=nve",
                    "Error: Failed to write memory at 0x00000a88",
                    "RRAMC ACCESSERRORADDR: 0x00000000",
                    "RRAMC CONFIG: 0x00000001",
                    "RRAMC BUFSTATUS: 0x00000000",
                    "flash retry 1/3 label=nve exit=1 nextDelaySec=2",
                    "flash attempt 2/4 label=nve",
                    "40637 bytes written at address 0x00000000",
                    "36 bytes written at address 0x000f0000",
                    "flash succeeded label=nve attempts=2",
                )
            )
        )

        diagnostics = matrix.openocd_diagnostics(path)

        joined = "\n".join(diagnostics)
        self.assertIn("flashAttemptsObserved=2/4", joined)
        self.assertIn("failedWriteCount=1 addresses=0x00000a88", joined)
        self.assertIn("rramc accessError=0x00000000 config=0x00000001", joined)
        self.assertIn("flashSuccess=nve:attempts2", joined)

    def _write_log(self, text: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "flash.log"
        path.write_text(text + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
