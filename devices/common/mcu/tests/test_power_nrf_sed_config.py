from __future__ import annotations

import unittest
import importlib.util
import re
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[4]
POWER_NRF_MCU = PROJECT_ROOT / "devices" / "power-nrf" / "mcu"
TBOT_MCU = PROJECT_ROOT / "devices" / "tbot" / "mcu"
LM20A_COMMON = PROJECT_ROOT / "devices" / "common" / "mcu" / "xiao_nrf54lm20a"
LM20A_SOURCE = LM20A_COMMON / "src" / "thread_device.c"
LM20A_OVERLAY = LM20A_COMMON / "boards" / "xiao_nrf54lm20a_nrf54lm20a_cpuapp.overlay"


def read_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def load_mcu_driver():
    script = PROJECT_ROOT / "devices" / "common" / "mcu" / "scripts" / "stock_zephyr_mcu.py"
    spec = importlib.util.spec_from_file_location("stock_zephyr_mcu_for_unittest", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Lm20aThreadSedConfigTests(unittest.TestCase):
    def test_each_product_uses_stock_openthread_sed_with_five_second_polling(self) -> None:
        for mcu in (POWER_NRF_MCU, TBOT_MCU):
            values = read_conf(mcu / "zephyr" / "prj.conf")

            self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD"), "y")
            self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD_SED"), "y")
            self.assertEqual(values.get("CONFIG_OPENTHREAD_POLL_PERIOD"), "5000")
            self.assertEqual(values.get("CONFIG_OPENTHREAD_COAP"), "y")
            self.assertEqual(values.get("CONFIG_OPENTHREAD_SRP_CLIENT"), "y")
            self.assertNotIn("CONFIG_BT", values)
            self.assertNotIn("CONFIG_CHIP", values)

    def test_coap_srp_and_txn1_contracts_are_explicit(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")

        self.assertIn('#define TXN1_MAGIC "TXN1"', source)
        self.assertIn("crc32_ieee(payload, payload_len)", source)
        self.assertIn('state_resource.mUriPath = "txing/v1/state"', source)
        self.assertIn('redcon_resource.mUriPath = "txing/v1/redcon"', source)
        self.assertIn("OT_COAP_CODE_GET", source)
        self.assertIn("OT_COAP_CODE_PUT", source)
        self.assertIn("TXING_REDCON_ON 3", source)
        self.assertIn("TXING_REDCON_OFF 4", source)
        self.assertIn('mName = "_txing-coap._udp"', source)
        self.assertIn("txt_type[] = TXING_LM20A_SRP_SERVICE_TYPE", source)
        self.assertIn('mKey = "pv"', source)
        self.assertIn("factory.coap_port", source)

        power_config = (POWER_NRF_MCU / "src" / "txing_lm20a_thread_config.h").read_text(
            encoding="ascii"
        )
        tbot_config = (TBOT_MCU / "src" / "txing_lm20a_thread_config.h").read_text(
            encoding="ascii"
        )
        self.assertIn('TXING_LM20A_SRP_SERVICE_TYPE "power-nrf"', power_config)
        self.assertIn('TXING_LM20A_SRP_SERVICE_TYPE "tbot"', tbot_config)
        self.assertIn('TXING_LM20A_DEFAULT_THING_NAME "tbot-unconfigured"', tbot_config)

    def test_srp_bootstrap_switches_to_sleepy_mode(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")

        self.assertIn("configure_thread_mode_locked(ot, true)", source)
        self.assertIn("otLinkSetPollPeriod(ot, CONFIG_OPENTHREAD_POLL_PERIOD)", source)
        self.assertIn("atomic_set(&srp_registration_accepted, 1)", source)
        self.assertIn("k_work_schedule(&sed_transition_work", source)
        self.assertIn("configure_thread_mode_locked(ot, false)", source)
        self.assertIn("Thread mode n with poll period", source)

    def test_redcon_controls_outputs_and_defers_the_sleep_transition(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")

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

    def test_startup_and_invalid_redcon_requests_cannot_enable_power(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")

        self.assertIn("static int redcon_level = TXING_REDCON_OFF;", source)
        self.assertIn("return set_outputs_for_redcon(TXING_REDCON_OFF);", source)
        redcon_handler = source.index("static void redcon_handler")
        validation = source.index(
            "!parse_redcon_request(message, &request) || request.version != TXING_PROTOCOL_VERSION",
            redcon_handler,
        )
        reject = source.index("OT_COAP_CODE_BAD_REQUEST", validation)
        output_change = source.index("set_outputs_for_redcon(request.redcon)", redcon_handler)
        self.assertLess(validation, reject)
        self.assertLess(reject, output_change)

    def test_release_and_sed_debug_share_exponential_sed_recovery(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")
        for mcu, prefix in ((POWER_NRF_MCU, "POWER_NRF"), (TBOT_MCU, "TBOT")):
            release = read_conf(mcu / "zephyr" / "release.conf")
            sed_debug = read_conf(mcu / "zephyr" / "sed-debug.conf")
            debug = read_conf(mcu / "zephyr" / "debug.conf")

            self.assertEqual(release.get(f"CONFIG_TXING_{prefix}_SED_RECOVERY"), "y")
            self.assertEqual(sed_debug.get(f"CONFIG_TXING_{prefix}_SED_RECOVERY"), "y")
            self.assertEqual(
                debug.get(f"CONFIG_TXING_{prefix}_RECEIVER_ON_DIAGNOSTICS"), "y"
            )
            self.assertNotIn(f"CONFIG_TXING_{prefix}_SED_RECOVERY", debug)

        delays_match = re.search(
            r"static const uint16_t sed_recovery_delays_seconds\[\] = \{(?P<delays>.*?)\};",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(delays_match)
        assert delays_match is not None
        delays = [int(value) for value in re.findall(r"\d+", delays_match.group("delays"))]
        self.assertEqual(delays, [20, 40, 80, 160, 320, 600])
        self.assertNotIn("SED_RECOVERY_MAX_ATTEMPTS", source)
        self.assertIn("index = ARRAY_SIZE(sed_recovery_delays_seconds) - 1", source)
        self.assertIn(
            "atomic_get(&recovery_attempts) < (int)ARRAY_SIZE(sed_recovery_delays_seconds) - 1",
            source,
        )
        self.assertIn(
            "k_work_schedule(&recovery_work, K_SECONDS(recovery_delay_seconds()))",
            source,
        )

        schedule_start = source.rindex("static void schedule_recovery")
        recovery_start = source.index("static void recovery_work_handler", schedule_start)
        recovery_handler = source[recovery_start : source.index("static int start_thread", recovery_start)]
        self.assertIn("if (redcon_level != TXING_REDCON_OFF || expected_receiver_on)", recovery_handler)
        self.assertIn("record_recovery_attempt();\n\trc = restart_thread_mode_locked(ot, false);", recovery_handler)
        self.assertIn("#elif IS_ENABLED(TXING_LM20A_RECEIVER_ON_DIAGNOSTICS_CONFIG)", recovery_handler)
        self.assertIn("rc = restart_thread_mode_locked(ot, true);", recovery_handler)
        self.assertIn(
            "if (rc != 0 || IS_ENABLED(TXING_LM20A_SED_RECOVERY_CONFIG))",
            recovery_handler,
        )

    def test_srp_acceptance_is_the_only_recovery_backoff_reset(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")
        callback_start = source.index(
            "static void srp_client_callback", source.index("static int start_srp")
        )
        callback = source[
            callback_start : source.index("static void sed_transition_work_handler", callback_start)
        ]

        self.assertEqual(source.count("atomic_set(&recovery_attempts, 0);"), 1)
        accepted = callback.index("atomic_set(&srp_registration_accepted, 1);")
        reset = callback.index("atomic_set(&recovery_attempts, 0);")
        self.assertLess(accepted, reset)
        self.assertIn("atomic_set(&srp_registration_accepted, 0);\n\t\tschedule_recovery();", callback)
        self.assertIn("(void)k_work_cancel_delayable(&recovery_work);", callback)

    def test_recovery_work_is_coalesced_until_srp_acceptance(self) -> None:
        source = LM20A_SOURCE.read_text(encoding="ascii")
        schedule_start = source.rindex("static void schedule_recovery")
        recovery_start = source.index("static void recovery_work_handler", schedule_start)
        scheduler = source[schedule_start:recovery_start]
        recovery_handler = source[recovery_start : source.index("static int start_thread", recovery_start)]

        self.assertIn("atomic_get(&recovery_pending) != 0", scheduler)
        self.assertIn("atomic_set(&recovery_pending, 1);", scheduler)
        self.assertIn("atomic_set(&recovery_pending, 0);", recovery_handler)

    def test_npm1300_battery_reading_is_on_demand_and_null_safe(self) -> None:
        values = read_conf(POWER_NRF_MCU / "zephyr" / "prj.conf")
        source = LM20A_SOURCE.read_text(encoding="ascii")

        self.assertEqual(values.get("CONFIG_SENSOR"), "y")
        self.assertIn("DT_NODELABEL(pmic_charger)", source)
        self.assertIn("sensor_sample_fetch_chan(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE)", source)
        self.assertIn("sensor_channel_get(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE", source)
        self.assertIn("sensor_value_to_milli(&voltage)", source)
        self.assertIn('"batteryMv\\\":%u}', source)
        self.assertIn('"batteryMv\\\":null}', source)
        self.assertIn("nPM1300 battery measurement unavailable", source)

    def test_split_nordic_clock_nodes_are_enabled(self) -> None:
        overlay = LM20A_OVERLAY.read_text(encoding="ascii")

        for node in ("xo", "lfclk", "xo24m"):
            self.assertIn(f'&{node} {{\n\tstatus = "okay";\n}};', overlay)

    def test_matter_chip_and_ble_redcon_are_absent(self) -> None:
        contents = "\n".join(
            path.read_text(encoding="ascii").lower()
            for path in (
                LM20A_SOURCE,
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

    def test_products_compile_the_single_shared_lm20a_implementation(self) -> None:
        for mcu in (POWER_NRF_MCU, TBOT_MCU):
            cmake = (mcu / "zephyr" / "CMakeLists.txt").read_text(encoding="ascii")
            self.assertIn("xiao_nrf54lm20a", cmake)
            self.assertIn("src/thread_device.c", cmake)
            self.assertFalse((mcu / "src" / "main.c").exists())

    def test_driver_exposes_tbot_build_profiles_openocd_and_txn1_writer(self) -> None:
        driver = load_mcu_driver()
        config = driver.device_config("tbot")

        self.assertEqual(config.board, "xiao_nrf54lm20a/nrf54lm20a/cpuapp")
        self.assertEqual(config.flash_runner, "openocd-nrf54lm20a")
        self.assertEqual(
            driver.build_dir("tbot", profile="sed-debug").name,
            "zephyr-xiao_nrf54lm20a_nrf54lm20a_cpuapp-sed-debug",
        )
        self.assertTrue(driver.build_profile("tbot").release_conf)
        self.assertTrue(driver.build_profile("tbot", profile="sed-debug").sed_debug_conf)
        self.assertEqual(driver.overlay_file("tbot"), driver.overlay_file("power-nrf"))
        command = [str(part) for part in driver.openocd_command("tbot", Path("factory.hex"))]
        self.assertIn("targets nrf54lm20a.cpu", command)
        self.assertIn("nrf54lm20a-load factory.hex", command)

        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append([str(arg) for arg in args])
            return None

        with patch.object(driver, "run", fake_run):
            driver.build_lm20a_thread_factory_hex(
                "tbot", "tbot-001", Path("dataset.hex"), Path("output.hex"), 5683
            )

        self.assertEqual(calls[0][2:5], ["write-hex", "tbot-001", "--dataset-tlvs"])
        self.assertEqual(calls[0][-1], "output.hex")


if __name__ == "__main__":
    unittest.main()
