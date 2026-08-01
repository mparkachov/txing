from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
POWER_NRF_MCU = PROJECT_ROOT / "devices" / "power-nrf" / "mcu"


def read_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class PowerNrfSedConfigTests(unittest.TestCase):
    def test_uses_stock_openthread_sed_with_five_second_polling(self) -> None:
        values = read_conf(POWER_NRF_MCU / "zephyr" / "prj.conf")

        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD_SED"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_POLL_PERIOD"), "5000")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_COAP"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_SRP_CLIENT"), "y")
        self.assertNotIn("CONFIG_BT", values)
        self.assertNotIn("CONFIG_CHIP", values)

    def test_coap_srp_and_txn1_contracts_are_explicit(self) -> None:
        source = (POWER_NRF_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertIn('#define TXN1_MAGIC "TXN1"', source)
        self.assertIn("crc32_ieee(payload, payload_len)", source)
        self.assertIn('state_resource.mUriPath = "txing/v1/state"', source)
        self.assertIn('redcon_resource.mUriPath = "txing/v1/redcon"', source)
        self.assertIn("OT_COAP_CODE_GET", source)
        self.assertIn("OT_COAP_CODE_PUT", source)
        self.assertIn("TXING_REDCON_ON 3", source)
        self.assertIn("TXING_REDCON_OFF 4", source)
        self.assertIn('mName = "_txing-coap._udp"', source)
        self.assertIn('txt_type[] = "power-nrf"', source)
        self.assertIn('mKey = "pv"', source)
        self.assertIn("factory.coap_port", source)

    def test_srp_bootstrap_switches_to_sleepy_mode(self) -> None:
        source = (POWER_NRF_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertIn("configure_thread_mode_locked(ot, true)", source)
        self.assertIn("otLinkSetPollPeriod(ot, CONFIG_OPENTHREAD_POLL_PERIOD)", source)
        self.assertIn("atomic_set(&srp_registration_accepted, 1)", source)
        self.assertIn("k_work_schedule(&sed_transition_work", source)
        self.assertIn("configure_thread_mode_locked(ot, false)", source)
        self.assertIn("Thread mode n with poll period", source)

    def test_redcon_controls_outputs_and_defers_the_sleep_transition(self) -> None:
        source = (POWER_NRF_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertIn("GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios)", source)
        self.assertIn("GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios)", source)
        self.assertIn("set_outputs_for_redcon(request.redcon)", source)
        self.assertIn("configure_thread_mode_locked(ot, true)", source)
        self.assertIn("send_state_response(message, message_info, OT_COAP_CODE_CHANGED);", source)
        self.assertIn("K_MSEC(SED_REDCON_RESPONSE_GRACE_MS)", source)
        self.assertIn("redcon_sleep_work_handler", source)
        self.assertIn("configure_thread_mode_locked(ot, false)", source)
        redcon_handler = source.index("static void redcon_handler")
        response_then_sleep = source.index(
            "send_state_response(message, message_info, OT_COAP_CODE_CHANGED);\n\t(void)k_work_schedule(&redcon_sleep_work",
            redcon_handler,
        )
        self.assertGreater(response_then_sleep, redcon_handler)

    def test_release_and_sed_debug_keep_recovery_sleepy_only(self) -> None:
        release = read_conf(POWER_NRF_MCU / "zephyr" / "release.conf")
        sed_debug = read_conf(POWER_NRF_MCU / "zephyr" / "sed-debug.conf")
        debug = read_conf(POWER_NRF_MCU / "zephyr" / "debug.conf")
        source = (POWER_NRF_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertEqual(release.get("CONFIG_TXING_POWER_NRF_SED_RECOVERY"), "y")
        self.assertEqual(sed_debug.get("CONFIG_TXING_POWER_NRF_SED_RECOVERY"), "y")
        self.assertEqual(
            debug.get("CONFIG_TXING_POWER_NRF_RECEIVER_ON_DIAGNOSTICS"), "y"
        )
        self.assertNotIn("CONFIG_TXING_POWER_NRF_SED_RECOVERY", debug)
        self.assertIn("SED_RECOVERY_MAX_ATTEMPTS 3", source)
        self.assertIn("restart_thread_mode_locked(ot, false)", source)
        self.assertIn("restart_thread_mode_locked(ot, true)", source)

    def test_npm1300_battery_reading_is_on_demand_and_null_safe(self) -> None:
        values = read_conf(POWER_NRF_MCU / "zephyr" / "prj.conf")
        source = (POWER_NRF_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertEqual(values.get("CONFIG_SENSOR"), "y")
        self.assertIn("DT_NODELABEL(pmic_charger)", source)
        self.assertIn("sensor_sample_fetch_chan(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE)", source)
        self.assertIn("sensor_channel_get(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE", source)
        self.assertIn("sensor_value_to_milli(&voltage)", source)
        self.assertIn('"batteryMv\\\":%u}', source)
        self.assertIn('"batteryMv\\\":null}', source)
        self.assertIn("nPM1300 battery measurement unavailable", source)

    def test_matter_chip_and_ble_redcon_are_absent(self) -> None:
        contents = "\n".join(
            path.read_text(encoding="ascii").lower()
            for path in (
                POWER_NRF_MCU / "src" / "main.c",
                POWER_NRF_MCU / "zephyr" / "CMakeLists.txt",
                POWER_NRF_MCU / "zephyr" / "prj.conf",
                POWER_NRF_MCU / "zephyr" / "debug.conf",
                POWER_NRF_MCU / "zephyr" / "sed-debug.conf",
                POWER_NRF_MCU / "zephyr" / "release.conf",
            )
        )

        self.assertNotIn("matter", contents)
        self.assertNotIn("chip", contents)
        self.assertNotIn("config_bt", contents)
        self.assertNotIn("ble redcon", contents)


if __name__ == "__main__":
    unittest.main()
