from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from board.motor_driver import (
    DEFAULT_DRIVE_CMD_RAW_MAX_SPEED,
    DEFAULT_DRIVE_CMD_RAW_MIN_SPEED,
    DEFAULT_DRIVE_PERCENT_MAX_SPEED,
    DEFAULT_DRIVE_RAW_MAX_SPEED,
    Drv8835MotorDriver,
    DriveHardwareConfig,
    PercentMotorDriverAdapter,
    _HardwareResources,
    _SysfsPwmChannel,
    clamp_speed,
    scale_speed,
    scale_speed_to_range,
)


class _FakePwmChannel:
    def __init__(self, *, period_ns: int = 50_000) -> None:
        self.period_ns = period_ns
        self.calls: list[int] = []
        self.closed = False

    def set_duty_cycle_ns(self, duty_cycle_ns: int) -> None:
        self.calls.append(duty_cycle_ns)

    def close(self) -> None:
        self.closed = True


class _FakeDirectionOutput:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.closed = False

    def on(self) -> None:
        self.events.append("on")

    def off(self) -> None:
        self.events.append("off")

    def close(self) -> None:
        self.closed = True


class _FakePinFactory:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeRawMotorDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.closed = False

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        self.calls.append((m1_speed, m2_speed))

    def close(self) -> None:
        self.closed = True


class MotorDriverTests(unittest.TestCase):
    def test_scale_speed_maps_percent_to_raw(self) -> None:
        self.assertEqual(
            scale_speed(
                100,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_max_speed=DEFAULT_DRIVE_RAW_MAX_SPEED,
            ),
            480,
        )
        self.assertEqual(
            scale_speed(
                50,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_max_speed=DEFAULT_DRIVE_RAW_MAX_SPEED,
            ),
            240,
        )
        self.assertEqual(
            scale_speed(
                -75,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_max_speed=DEFAULT_DRIVE_RAW_MAX_SPEED,
            ),
            -360,
        )

    def test_scale_speed_to_range_maps_zero_and_non_zero_percent(self) -> None:
        self.assertEqual(
            scale_speed_to_range(
                0,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=50,
                target_max_speed=250,
            ),
            0,
        )
        self.assertEqual(
            scale_speed_to_range(
                1,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=50,
                target_max_speed=250,
            ),
            50,
        )
        self.assertEqual(
            scale_speed_to_range(
                50,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=50,
                target_max_speed=250,
            ),
            149,
        )
        self.assertEqual(
            scale_speed_to_range(
                -100,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=50,
                target_max_speed=250,
            ),
            -250,
        )

    def test_scale_speed_to_range_preserves_linear_behavior_when_min_is_zero(self) -> None:
        self.assertEqual(
            scale_speed_to_range(
                1,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=DEFAULT_DRIVE_CMD_RAW_MIN_SPEED,
                target_max_speed=DEFAULT_DRIVE_CMD_RAW_MAX_SPEED,
            ),
            5,
        )
        self.assertEqual(
            scale_speed_to_range(
                50,
                source_max_speed=DEFAULT_DRIVE_PERCENT_MAX_SPEED,
                target_min_speed=DEFAULT_DRIVE_CMD_RAW_MIN_SPEED,
                target_max_speed=DEFAULT_DRIVE_CMD_RAW_MAX_SPEED,
            ),
            240,
        )

    def test_clamp_speed_limits_to_range(self) -> None:
        self.assertEqual(clamp_speed(481, DEFAULT_DRIVE_RAW_MAX_SPEED), 480)
        self.assertEqual(clamp_speed(-481, DEFAULT_DRIVE_RAW_MAX_SPEED), -480)
        self.assertEqual(clamp_speed(123, DEFAULT_DRIVE_RAW_MAX_SPEED), 123)

    def test_percent_adapter_scales_and_closes_delegate(self) -> None:
        raw_driver = _FakeRawMotorDriver()
        adapter = PercentMotorDriverAdapter(
            raw_motor_driver=raw_driver,
            percent_max_speed=100,
            raw_min_speed=50,
            raw_max_speed=480,
        )

        adapter.setSpeeds(1, -50)
        adapter.close()

        self.assertEqual(raw_driver.calls, [(50, -263)])
        self.assertTrue(raw_driver.closed)

    def test_percent_adapter_rejects_invalid_raw_range(self) -> None:
        with self.assertRaises(ValueError):
            PercentMotorDriverAdapter(
                raw_motor_driver=_FakeRawMotorDriver(),
                raw_min_speed=250,
                raw_max_speed=250,
            )

    def test_drv8835_driver_applies_direction_and_duty(self) -> None:
        left_pwm = _FakePwmChannel(period_ns=1000)
        right_pwm = _FakePwmChannel(period_ns=1000)
        left_direction = _FakeDirectionOutput()
        right_direction = _FakeDirectionOutput()
        pin_factory = _FakePinFactory()
        resources = _HardwareResources(
            left_pwm=left_pwm,
            right_pwm=right_pwm,
            left_direction=left_direction,
            right_direction=right_direction,
            pin_factory=pin_factory,
        )
        driver = Drv8835MotorDriver(
            config=DriveHardwareConfig(raw_max_speed=480),
            resources=resources,
        )

        driver.setSpeeds(240, -120)
        driver.close()

        self.assertEqual(left_direction.events[:2], ["off", "off"])
        self.assertEqual(right_direction.events[:2], ["off", "on"])
        self.assertIn(500, left_pwm.calls)
        self.assertIn(250, right_pwm.calls)
        self.assertTrue(left_direction.closed)
        self.assertTrue(right_direction.closed)
        self.assertTrue(left_pwm.closed)
        self.assertTrue(right_pwm.closed)
        self.assertTrue(pin_factory.closed)

    def test_drv8835_driver_honors_inversion(self) -> None:
        left_pwm = _FakePwmChannel(period_ns=1000)
        right_pwm = _FakePwmChannel(period_ns=1000)
        left_direction = _FakeDirectionOutput()
        right_direction = _FakeDirectionOutput()
        resources = _HardwareResources(
            left_pwm=left_pwm,
            right_pwm=right_pwm,
            left_direction=left_direction,
            right_direction=right_direction,
            pin_factory=None,
        )
        driver = Drv8835MotorDriver(
            config=DriveHardwareConfig(
                raw_max_speed=480,
                left_inverted=True,
                right_inverted=True,
            ),
            resources=resources,
        )

        driver.setSpeeds(100, -100)

        self.assertEqual(left_direction.events[-1], "on")
        self.assertEqual(right_direction.events[-1], "off")

    def test_sysfs_pwm_channel_writes_expected_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pwm_root = Path(tmpdir)
            chip_path = pwm_root / "pwmchip0"
            chip_path.mkdir()
            export_path = chip_path / "export"
            unexport_path = chip_path / "unexport"
            export_path.write_text("", encoding="utf-8")
            unexport_path.write_text("", encoding="utf-8")

            def _on_export(chip_dir: Path, channel: int) -> None:
                pwm_path = chip_dir / f"pwm{channel}"
                pwm_path.mkdir()
                (pwm_path / "enable").write_text("", encoding="utf-8")
                (pwm_path / "period").write_text("", encoding="utf-8")
                (pwm_path / "duty_cycle").write_text("", encoding="utf-8")

            pwm_channel = _SysfsPwmChannel(
                pwm_sysfs_root=pwm_root,
                chip=0,
                channel=0,
                frequency_hz=20_000,
                on_export=_on_export,
            )
            pwm_channel.set_duty_cycle_ns(12_500)
            pwm_channel.close()

            self.assertEqual(export_path.read_text(encoding="utf-8").strip(), "0")
            self.assertEqual(unexport_path.read_text(encoding="utf-8").strip(), "0")
            self.assertEqual((chip_path / "pwm0" / "enable").read_text(encoding="utf-8").strip(), "0")
            self.assertEqual((chip_path / "pwm0" / "period").read_text(encoding="utf-8").strip(), "50000")
            self.assertEqual((chip_path / "pwm0" / "duty_cycle").read_text(encoding="utf-8").strip(), "0")

    def test_ensure_lgpio_workdir_creates_tempdir_when_unset(self) -> None:
        original_workdir = Drv8835MotorDriver._auto_lgpio_workdir
        created_workdir = None
        try:
            Drv8835MotorDriver._auto_lgpio_workdir = None
            with patch.dict(os.environ, {}, clear=True):
                Drv8835MotorDriver._ensure_lgpio_workdir()
                created_workdir = Drv8835MotorDriver._auto_lgpio_workdir
                self.assertIsNotNone(created_workdir)
                self.assertIn("LG_WD", os.environ)
                workdir = Path(os.environ["LG_WD"])
                self.assertTrue(workdir.is_dir())
                self.assertTrue(workdir.name.startswith("txing-lgpio-"))
        finally:
            if created_workdir is not None and created_workdir is not original_workdir:
                created_workdir.cleanup()
            Drv8835MotorDriver._auto_lgpio_workdir = original_workdir


if __name__ == "__main__":
    unittest.main()
