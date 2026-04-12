from __future__ import annotations

from argparse import Namespace
import unittest
from unittest.mock import MagicMock, patch

import board.motor_raw as motor_raw


def _make_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "left": 240,
        "right": 240,
        "duration": 0.01,
        "skip_service_check": False,
        "service_name": "board",
        "drive_raw_max_speed": 480,
        "drive_pwm_hz": 20_000,
        "drive_pwm_chip": 0,
        "drive_left_pwm_channel": 0,
        "drive_right_pwm_channel": 1,
        "drive_gpio_chip": 0,
        "drive_left_dir_gpio": 5,
        "drive_right_dir_gpio": 6,
        "drive_left_inverted": False,
        "drive_right_inverted": False,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


class _FakeMotorDriver:
    def __init__(self, **_kwargs: object) -> None:
        self.calls: list[tuple[int, int]] = []
        self.closed = False

    def setSpeeds(self, left: int, right: int) -> None:
        self.calls.append((left, right))

    def close(self) -> None:
        self.closed = True


class MotorRawTests(unittest.TestCase):
    def test_service_check_raises_when_service_is_active(self) -> None:
        with patch.object(motor_raw.subprocess, "run", return_value=MagicMock(returncode=0)):
            with self.assertRaises(RuntimeError):
                motor_raw._ensure_board_service_not_running("board")

    def test_service_check_passes_when_service_is_inactive(self) -> None:
        with patch.object(motor_raw.subprocess, "run", return_value=MagicMock(returncode=3)):
            motor_raw._ensure_board_service_not_running("board")

    def test_main_runs_motor_driver_and_stops(self) -> None:
        fake_driver = _FakeMotorDriver()
        with (
            patch.object(motor_raw, "_parse_args", return_value=_make_args()),
            patch.object(motor_raw, "_configure_logging"),
            patch.object(motor_raw, "_ensure_board_service_not_running"),
            patch.object(motor_raw, "Drv8835MotorDriver", return_value=fake_driver),
        ):
            motor_raw.main()

        self.assertEqual(fake_driver.calls[0], (240, 240))
        self.assertTrue(fake_driver.closed)

    def test_main_rejects_out_of_range_value(self) -> None:
        with (
            patch.object(motor_raw, "_parse_args", return_value=_make_args(left=999)),
            patch.object(motor_raw, "_configure_logging"),
        ):
            with self.assertRaises(SystemExit) as captured:
                motor_raw.main()

        self.assertEqual(captured.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
