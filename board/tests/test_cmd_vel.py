from __future__ import annotations

import time
import unittest

from board.cmd_vel import (
    DriveState,
    MAX_WHEEL_LINEAR_SPEED_MPS,
    MAX_SPEED,
    TRACK_WIDTH_M,
    CmdVelController,
    Twist,
    Vector3,
    build_cmd_vel_topic,
    mix_twist_to_tank_speeds,
    parse_twist_payload,
)


class _FakeMotorDriver:
    MAX_SPEED = MAX_SPEED

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        self.calls.append((m1_speed, m2_speed))


class _FlakyMotorDriver:
    MAX_SPEED = MAX_SPEED

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self._first_non_zero_fails = True

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        self.calls.append((m1_speed, m2_speed))
        if self._first_non_zero_fails and (m1_speed, m2_speed) != (0, 0):
            self._first_non_zero_fails = False
            raise RuntimeError("simulated motor write failure")


class CmdVelContractTests(unittest.TestCase):
    def test_builds_topic(self) -> None:
        self.assertEqual(build_cmd_vel_topic("txing"), "txing/board/cmd_vel")

    def test_parses_valid_twist_payload(self) -> None:
        twist = parse_twist_payload(
            {
                "linear": {"x": 1, "y": 0, "z": 0},
                "angular": {"x": 0, "y": 0, "z": -1},
            }
        )

        self.assertEqual(
            twist,
            Twist(
                linear=Vector3(x=1.0, y=0.0, z=0.0),
                angular=Vector3(x=0.0, y=0.0, z=-1.0),
            ),
        )

    def test_rejects_invalid_twist_payload(self) -> None:
        self.assertIsNone(
            parse_twist_payload(
                {
                    "linear": {"x": True, "y": 0, "z": 0},
                    "angular": {"x": 0, "y": 0, "z": 0},
                }
            )
        )
        self.assertIsNone(parse_twist_payload({"linear": {"x": 1, "y": 0, "z": 0}}))

    def test_mixes_twist_into_tank_speeds(self) -> None:
        self.assertEqual(
            mix_twist_to_tank_speeds(
                Twist(
                    linear=Vector3(x=0.5, y=0.0, z=0.0),
                    angular=Vector3(x=0.0, y=0.0, z=0.0),
                )
            ),
            (100, 100),
        )
        self.assertEqual(
            mix_twist_to_tank_speeds(
                Twist(
                    linear=Vector3(x=0.0, y=0.0, z=0.0),
                    angular=Vector3(x=0.0, y=0.0, z=1.0),
                )
            ),
            (-28, 28),
        )
        self.assertEqual(
            mix_twist_to_tank_speeds(
                Twist(
                    linear=Vector3(x=0.2, y=0.0, z=0.0),
                    angular=Vector3(x=0.0, y=0.0, z=0.2),
                )
            ),
            (34, 46),
        )
        self.assertEqual(
            mix_twist_to_tank_speeds(
                Twist(
                    linear=Vector3(x=0.5, y=0.0, z=0.0),
                    angular=Vector3(x=0.0, y=0.0, z=1.0),
                )
            ),
            (72, 100),
        )

    def test_controller_stops_after_watchdog_timeout(self) -> None:
        motor_driver = _FakeMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
            watchdog_timeout_seconds=0.01,
            watchdog_poll_interval=0.001,
        )
        controller.start()

        try:
            handled = controller.handle_message(
                {
                    "linear": {"x": 0.5, "y": 0, "z": 0},
                    "angular": {"x": 0, "y": 0, "z": 0},
                }
            )
            self.assertTrue(handled)
            time.sleep(0.05)
        finally:
            controller.close()

        self.assertEqual(motor_driver.calls[0], (MAX_SPEED, MAX_SPEED))
        self.assertIn((0, 0), motor_driver.calls)

    def test_controller_stops_on_disconnect(self) -> None:
        motor_driver = _FakeMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
            watchdog_timeout_seconds=1.0,
            watchdog_poll_interval=0.01,
        )
        controller.start()

        try:
            controller.handle_message(
                {
                    "linear": {"x": 0.2, "y": 0, "z": 0},
                    "angular": {"x": 0, "y": 0, "z": -0.2},
                }
            )
            controller.handle_disconnect("lost connection")
        finally:
            controller.close()

        self.assertEqual(motor_driver.calls[0], (46, 34))
        self.assertIn((0, 0), motor_driver.calls)

    def test_controller_ignores_malformed_payloads(self) -> None:
        motor_driver = _FakeMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
            watchdog_timeout_seconds=1.0,
            watchdog_poll_interval=0.01,
        )
        controller.start()

        try:
            handled = controller.handle_message({"linear": {"x": 1}})
        finally:
            controller.close()

        self.assertFalse(handled)
        self.assertEqual(motor_driver.calls, [(0, 0)])

    def test_controller_warns_and_ignores_unsupported_axes(self) -> None:
        motor_driver = _FakeMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
        )

        try:
            with self.assertLogs("board.cmd_vel", level="WARNING") as captured:
                handled = controller.handle_message(
                    {
                        "linear": {"x": 0.5, "y": 0.3, "z": 0.1},
                        "angular": {"x": 0.2, "y": 0.4, "z": 0.0},
                    }
                )
        finally:
            controller.close()

        self.assertTrue(handled)
        self.assertEqual(motor_driver.calls[0], (MAX_SPEED, MAX_SPEED))
        self.assertIn("Ignoring unsupported cmd_vel axes", "\n".join(captured.output))

    def test_uses_temporary_phase_motion_constants(self) -> None:
        self.assertEqual(MAX_SPEED, 100)
        self.assertEqual(TRACK_WIDTH_M, 0.28)
        self.assertEqual(MAX_WHEEL_LINEAR_SPEED_MPS, 0.5)

    def test_controller_exposes_current_drive_state(self) -> None:
        motor_driver = _FakeMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
        )

        self.assertEqual(controller.get_drive_state(), DriveState(0, 0, 0))

        try:
            controller.handle_message(
                {
                    "linear": {"x": 0.2, "y": 0, "z": 0},
                    "angular": {"x": 0, "y": 0, "z": 0.2},
                }
            )
            self.assertEqual(controller.get_drive_state(), DriveState(34, 46, 1))
            controller.stop(reason="test stop")
            self.assertEqual(controller.get_drive_state(), DriveState(0, 0, 2))
        finally:
            controller.close()

    def test_controller_rolls_back_to_stopped_state_when_motor_write_fails(self) -> None:
        motor_driver = _FlakyMotorDriver()
        controller = CmdVelController(
            thing_name="txing",
            motor_driver=motor_driver,
        )

        self.assertEqual(controller.get_drive_state(), DriveState(0, 0, 0))
        controller.handle_message(
            {
                "linear": {"x": 0.2, "y": 0, "z": 0},
                "angular": {"x": 0, "y": 0, "z": 0},
            }
        )
        self.assertEqual(controller.get_drive_state(), DriveState(0, 0, 0))
        self.assertGreaterEqual(len(motor_driver.calls), 2)
        self.assertEqual(motor_driver.calls[0], (40, 40))
        self.assertEqual(motor_driver.calls[1], (0, 0))
