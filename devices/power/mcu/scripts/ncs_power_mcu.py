#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


MCU_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MCU_DIR.parents[2]
SHARED_SCRIPT = PROJECT_ROOT / "devices" / "common" / "mcu" / "scripts" / "ncs_mcu.py"

sys.argv = [
    str(SHARED_SCRIPT),
    "--mcu-dir",
    str(MCU_DIR),
    "--device-label",
    "power",
    *sys.argv[1:],
]
runpy.run_path(str(SHARED_SCRIPT), run_name="__main__")
