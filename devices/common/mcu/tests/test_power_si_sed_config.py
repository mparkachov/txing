from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
POWER_SI_MCU = PROJECT_ROOT / "devices" / "power-si" / "mcu"


def read_prj_conf() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (POWER_SI_MCU / "zephyr" / "prj.conf").read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class PowerSiSedConfigTests(unittest.TestCase):
    def test_power_si_uses_stock_openthread_sed_config(self) -> None:
        values = read_prj_conf()

        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD_SED"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_POLL_PERIOD"), "5000")

    def test_power_si_app_does_not_force_receiver_on_mode(self) -> None:
        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertNotIn("mRxOnWhenIdle = true", source)
        self.assertIn("mRxOnWhenIdle = false", source)
        self.assertIn("otLinkSetPollPeriod(ot, CONFIG_OPENTHREAD_POLL_PERIOD)", source)


if __name__ == "__main__":
    unittest.main()
