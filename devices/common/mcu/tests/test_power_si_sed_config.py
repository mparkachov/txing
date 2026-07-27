from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
POWER_SI_MCU = PROJECT_ROOT / "devices" / "power-si" / "mcu"


def read_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def read_prj_conf() -> dict[str, str]:
    return read_conf(POWER_SI_MCU / "zephyr" / "prj.conf")


class PowerSiSedConfigTests(unittest.TestCase):
    def test_power_si_uses_stock_openthread_sed_config(self) -> None:
        values = read_prj_conf()

        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_MTD_SED"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_POLL_PERIOD"), "5000")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_MIN_RECEIVE_ON_AFTER"), "5504")
        self.assertEqual(values.get("CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE"), "4096")
        self.assertNotIn("CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE", values)

    def test_debug_build_has_serial_diagnostics_without_radio_power_override(self) -> None:
        values = read_conf(POWER_SI_MCU / "zephyr" / "debug.conf")

        self.assertEqual(values.get("CONFIG_SERIAL"), "y")
        self.assertEqual(values.get("CONFIG_OPENTHREAD_SHELL"), "y")
        self.assertEqual(values.get("CONFIG_TXING_POWER_SI_SRP_PSA_DIAGNOSTICS"), "y")
        self.assertNotIn("CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE", values)
        self.assertNotIn("CONFIG_TXING_POWER_SI_TEST_TX_POWER_DBM", values)

    def test_sed_debug_uses_sed_only_recovery_policy(self) -> None:
        debug_values = read_conf(POWER_SI_MCU / "zephyr" / "sed-debug.conf")

        self.assertEqual(
            debug_values.get("CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST"), "y"
        )
        self.assertEqual(
            debug_values.get("CONFIG_TXING_POWER_SI_SED_REDCON_LINK_MODE_TEST"),
            "y",
        )
        self.assertNotIn(
            "CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST",
            read_conf(POWER_SI_MCU / "zephyr" / "debug.conf"),
        )

    def test_release_only_overrides_sed_debug_observability(self) -> None:
        values = read_conf(POWER_SI_MCU / "zephyr" / "release.conf")

        for key in (
            "CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST",
            "CONFIG_TXING_POWER_SI_SED_REDCON_LINK_MODE_TEST",
            "CONFIG_PM",
            "CONFIG_TICKLESS_KERNEL",
        ):
            self.assertNotIn(key, values, key)
        self.assertEqual(values.get("CONFIG_SERIAL"), "y")
        self.assertEqual(values.get("CONFIG_ADC"), "y")
        self.assertEqual(values.get("CONFIG_PM_DEVICE"), "y")
        self.assertEqual(values.get("CONFIG_PM_DEVICE_SYSTEM_MANAGED"), "n")
        self.assertEqual(
            values.get("CONFIG_TXING_POWER_SI_BATTERY_REPORTING"), "y"
        )
        for key in (
            "CONFIG_CONSOLE",
            "CONFIG_UART_CONSOLE",
            "CONFIG_PRINTK",
            "CONFIG_BOOT_BANNER",
            "CONFIG_LOG",
            "CONFIG_LOG_BACKEND_UART",
            "CONFIG_LOG_MODE_IMMEDIATE",
            "CONFIG_SHELL",
            "CONFIG_SHELL_BACKEND_SERIAL",
            "CONFIG_NET_SHELL",
            "CONFIG_OPENTHREAD_SHELL",
            "CONFIG_OPENTHREAD_DEBUG",
            "CONFIG_TXING_POWER_SI_SRP_PSA_DIAGNOSTICS",
            "CONFIG_TXING_POWER_SI_PM_TRANSITION_DIAGNOSTICS",
        ):
            self.assertEqual(values.get(key), "n", key)
        self.assertNotIn(
            "CONFIG_TXING_POWER_SI_SED_REDCON_LINK_MODE_TEST",
            read_conf(POWER_SI_MCU / "zephyr" / "debug.conf"),
        )

    def test_release_alone_reports_xiao_mg24_battery_voltage(self) -> None:
        for conf in ("prj.conf", "debug.conf", "sed-debug.conf"):
            self.assertNotIn(
                "CONFIG_TXING_POWER_SI_BATTERY_REPORTING",
                read_conf(POWER_SI_MCU / "zephyr" / conf),
            )

        overlay = (
            POWER_SI_MCU / "zephyr" / "boards" / "xiao_mg24.overlay"
        ).read_text(encoding="ascii")
        self.assertIn('compatible = "txing-battery-divider"', overlay)
        self.assertIn("io-channels = <&adc0 7>", overlay)
        self.assertIn("enable-gpios = <&gpiod 3 GPIO_ACTIVE_HIGH>", overlay)
        self.assertIn('zephyr,gain = "ADC_GAIN_1_2"', overlay)
        self.assertIn("zephyr,input-positive = <IADC_INPUT_PD4>", overlay)
        self.assertIn('zephyr,reference = "ADC_REF_INTERNAL"', overlay)
        self.assertIn("zephyr,vref-mv = <1210>", overlay)

        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")
        self.assertIn("CONFIG_TXING_POWER_SI_BATTERY_REPORTING", source)
        self.assertIn("pm_device_action_run(battery_adc.dev", source)
        self.assertIn("gpio_pin_set_dt(&battery_enable, 1)", source)
        self.assertIn("BATTERY_DIVIDER_SETTLE_MS 30", source)
        self.assertIn("millivolts *= BATTERY_DIVIDER_RATIO", source)
        self.assertIn('\\"batteryMv\\":%u', source)
        self.assertIn('\\"batteryMv\\":null', source)

    def test_sed_debug_alone_logs_silabs_sleep_mode_changes(self) -> None:
        sed_debug_values = read_conf(POWER_SI_MCU / "zephyr" / "sed-debug.conf")

        self.assertEqual(sed_debug_values.get("CONFIG_PM"), "y")
        self.assertEqual(sed_debug_values.get("CONFIG_TICKLESS_KERNEL"), "y")
        self.assertEqual(
            sed_debug_values.get("CONFIG_TXING_POWER_SI_PM_TRANSITION_DIAGNOSTICS"),
            "y",
        )
        for conf in ("prj.conf", "debug.conf"):
            self.assertNotIn(
                "CONFIG_TXING_POWER_SI_PM_TRANSITION_DIAGNOSTICS",
                read_conf(POWER_SI_MCU / "zephyr" / conf),
            )

        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")
        self.assertIn("sl_power_manager_subscribe_em_transition_event", source)
        self.assertIn("SL_POWER_MANAGER_EVENT_TRANSITION_ENTERING_EM1", source)
        self.assertIn("SL_POWER_MANAGER_EVENT_TRANSITION_ENTERING_EM2", source)
        self.assertIn("Silicon Labs PM sleep mode selected: %s", source)
        self.assertIn("Silicon Labs PM sleep mode changed: %s -> %s", source)
        self.assertNotIn("SL_POWER_MANAGER_EVENT_TRANSITION_ENTERING_EM0 |", source)

    def test_sed_debug_retains_the_common_coap_redcon_service(self) -> None:
        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertIn('redcon_resource.mUriPath = "txing/v1/redcon"', source)
        self.assertIn("redcon_resource.mHandler = redcon_handler", source)
        self.assertIn("otCoapAddResource(ot, &redcon_resource)", source)
        self.assertIn("otCoapMessageGetCode(message) != OT_COAP_CODE_PUT", source)
        self.assertIn(
            "request.redcon != TXING_REDCON_ON && request.redcon != TXING_REDCON_OFF",
            source,
        )
        self.assertIn("set_outputs_for_redcon(request.redcon)", source)

        self.assertIn("apply_sed_debug_redcon_thread_mode(request.redcon)", source)
        self.assertIn("SED debug REDCON %d switched Thread link mode to %s", source)
        self.assertIn('static const uint8_t txt_profile[] = "sed-debug"', source)
        self.assertIn('.mKey = "profile"', source)
        self.assertIn("gpio_pin_set_dt(&power_gpio", source)
        self.assertIn("gpio_pin_set_dt(&led_gpio", source)
        self.assertIn("start_thread(ot) != 0 || start_coap(ot) != 0 || start_srp(ot) != 0", source)

    def test_power_si_app_transitions_to_sed_after_srp_registration(self) -> None:
        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")

        self.assertIn("Thread SRP bootstrap mode configured: rxOnWhenIdle=1", source)
        self.assertIn("SRP update accepted", source)
        self.assertIn("k_work_schedule(&sed_transition_work", source)
        self.assertIn("switch_thread_to_sed_mode_locked", source)
        self.assertIn(
            "Thread SED link mode configured after SRP registration: rxOnWhenIdle=0",
            source,
        )
        self.assertIn("Thread switched to SED mode after SRP registration", source)
        self.assertIn("CONFIG_TXING_POWER_SI_SED_RECOVERY_TEST", source)
        self.assertIn("restart_thread_in_requested_mode_locked", source)
        self.assertIn("Thread restarted in SED mode during SED recovery", source)
        self.assertIn("#define SED_RECOVERY_MAX_ATTEMPTS 3", source)
        self.assertIn("schedule_sed_recovery", source)
        self.assertIn("Thread requested link-mode recovery exhausted", source)
        self.assertIn("link_mode.mRxOnWhenIdle = receiver_on_when_idle", source)
        self.assertIn("configure_thread_mtd_mode_locked(ot, false)", source)
        self.assertIn("otLinkSetPollPeriod(ot, CONFIG_OPENTHREAD_POLL_PERIOD)", source)
        self.assertIn("atomic_set(&sed_mode_active, 1)", source)
        self.assertIn("#define SED_FALLBACK_GRACE_SECONDS 20", source)
        self.assertIn("Thread SED mode did not remain attached", source)
        self.assertIn("restart_thread_in_bootstrap_mode_locked", source)
        self.assertIn("Thread restarted in SRP bootstrap mode after SED fallback", source)
        self.assertIn("atomic_set(&sed_transition_failed, 1)", source)
        self.assertNotIn("CONFIG_TXING_POWER_SI_TEST_TX_POWER_OVERRIDE", source)
        self.assertNotIn("Thread radio TX power override", source)

    def test_sed_debug_redcon_transitions_are_gated_and_keep_srp_running(self) -> None:
        source = (POWER_SI_MCU / "src" / "main.c").read_text(encoding="ascii")
        kconfig = (POWER_SI_MCU / "zephyr" / "Kconfig").read_text(encoding="ascii")

        self.assertIn("CONFIG_TXING_POWER_SI_SED_REDCON_LINK_MODE_TEST", source)
        self.assertIn("thread_receiver_on_requested", source)
        self.assertIn("thread_sed_mode_requested", source)
        self.assertIn("configure_thread_receiver_on_mode_locked", source)
        self.assertIn("configure_thread_mtd_mode_locked(ot, false)", source)
        self.assertIn("k_work_cancel_delayable(&sed_fallback_work)", source)
        self.assertIn("requested link-mode recovery", source)
        self.assertIn("Use REDCON to switch sed-debug link mode", kconfig)
        self.assertIn("retains the existing Thread child and SRP service", kconfig)


if __name__ == "__main__":
    unittest.main()
