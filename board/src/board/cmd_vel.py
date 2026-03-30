from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger("board.cmd_vel")

# Temporary phase constants until per-robot calibration and hardware mapping are
# added to runtime config. The current runtime scale is signed percent effort.
MAX_SPEED = 100
TRACK_WIDTH_M = 0.28
MAX_WHEEL_LINEAR_SPEED_MPS = 0.50


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Twist:
    linear: Vector3
    angular: Vector3


@dataclass(frozen=True)
class DriveState:
    left_speed: int
    right_speed: int
    sequence: int


class _MotorDriverStub:
    MAX_SPEED = MAX_SPEED

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        LOGGER.debug(
            "motors.setSpeeds(m1_speed=%s, m2_speed=%s)",
            m1_speed,
            m2_speed,
        )


motors = _MotorDriverStub()


def build_cmd_vel_topic(thing_name: str) -> str:
    return f"{thing_name}/board/cmd_vel"


def _coerce_axis_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_vector3(payload: Any) -> Vector3 | None:
    if not isinstance(payload, dict):
        return None

    x = _coerce_axis_value(payload.get("x"))
    y = _coerce_axis_value(payload.get("y"))
    z = _coerce_axis_value(payload.get("z"))
    if x is None or y is None or z is None:
        return None
    return Vector3(x=x, y=y, z=z)


def parse_twist_payload(payload: Any) -> Twist | None:
    if not isinstance(payload, dict):
        return None

    linear = _parse_vector3(payload.get("linear"))
    angular = _parse_vector3(payload.get("angular"))
    if linear is None or angular is None:
        return None
    return Twist(linear=linear, angular=angular)


def _clamp_unit_interval(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _find_unsupported_axes(twist: Twist) -> list[str]:
    unsupported_axes: list[str] = []
    if twist.linear.y != 0.0:
        unsupported_axes.append(f"linear.y={twist.linear.y:.3f}")
    if twist.linear.z != 0.0:
        unsupported_axes.append(f"linear.z={twist.linear.z:.3f}")
    if twist.angular.x != 0.0:
        unsupported_axes.append(f"angular.x={twist.angular.x:.3f}")
    if twist.angular.y != 0.0:
        unsupported_axes.append(f"angular.y={twist.angular.y:.3f}")
    return unsupported_axes


def mix_twist_to_tank_speeds(
    twist: Twist,
    *,
    track_width_m: float = TRACK_WIDTH_M,
    max_wheel_linear_speed_mps: float = MAX_WHEEL_LINEAR_SPEED_MPS,
    max_speed: int = MAX_SPEED,
) -> tuple[int, int]:
    if track_width_m <= 0.0:
        raise ValueError("track_width_m must be positive")
    if max_wheel_linear_speed_mps <= 0.0:
        raise ValueError("max_wheel_linear_speed_mps must be positive")

    half_track_width_m = track_width_m / 2.0
    left_wheel_linear_speed = twist.linear.x - (twist.angular.z * half_track_width_m)
    right_wheel_linear_speed = twist.linear.x + (twist.angular.z * half_track_width_m)

    left = _clamp_unit_interval(left_wheel_linear_speed / max_wheel_linear_speed_mps)
    right = _clamp_unit_interval(right_wheel_linear_speed / max_wheel_linear_speed_mps)

    return (
        int(round(left * max_speed)),
        int(round(right * max_speed)),
    )


class CmdVelController:
    def __init__(
        self,
        *,
        thing_name: str,
        motor_driver: Any = motors,
        max_speed: int = MAX_SPEED,
        watchdog_timeout_seconds: float = 0.5,
        watchdog_poll_interval: float = 0.05,
    ) -> None:
        self._thing_name = thing_name
        self._topic = build_cmd_vel_topic(thing_name)
        self._motor_driver = motor_driver
        self._max_speed = max_speed
        self._watchdog_timeout_seconds = watchdog_timeout_seconds
        self._watchdog_poll_interval = watchdog_poll_interval
        self._last_message_monotonic: float | None = None
        self._last_speeds = (0, 0)
        self._drive_state_sequence = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._closed = False

    @property
    def topic(self) -> str:
        return self._topic

    def get_drive_state(self) -> DriveState:
        with self._lock:
            return DriveState(
                left_speed=self._last_speeds[0],
                right_speed=self._last_speeds[1],
                sequence=self._drive_state_sequence,
            )

    def start(self) -> None:
        if self._watchdog_thread is not None:
            return

        self._watchdog_thread = threading.Thread(
            target=self._run_watchdog,
            name="txing-board-cmd-vel-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=max(1.0, self._watchdog_timeout_seconds))
        self.stop(reason="cmd_vel controller closed", force=True)
        with self._lock:
            self._closed = True

    def handle_message(self, payload: Any) -> bool:
        twist = parse_twist_payload(payload)
        if twist is None:
            LOGGER.warning(
                "Ignored malformed cmd_vel payload on %s: %s",
                self._topic,
                json.dumps(payload, sort_keys=True),
            )
            return False

        with self._lock:
            if self._closed:
                return False
            self._last_message_monotonic = time.monotonic()

        unsupported_axes = _find_unsupported_axes(twist)
        if unsupported_axes:
            LOGGER.warning(
                "Ignoring unsupported cmd_vel axes on %s: %s",
                self._topic,
                ", ".join(unsupported_axes),
            )

        left_speed, right_speed = mix_twist_to_tank_speeds(
            twist,
            max_speed=self._max_speed,
        )
        self._apply_speeds(
            left_speed,
            right_speed,
            reason=(
                "cmd_vel linear.x="
                f"{twist.linear.x:.3f} angular.z={twist.angular.z:.3f}"
            ),
        )
        return True

    def handle_disconnect(self, reason: str) -> None:
        self.stop(reason=reason, force=True)

    def stop(self, *, reason: str, force: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._last_message_monotonic = None
        self._apply_speeds(0, 0, reason=reason, force=force)

    def _apply_speeds(
        self,
        left_speed: int,
        right_speed: int,
        *,
        reason: str,
        force: bool = False,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            state_changed = self._last_speeds != (left_speed, right_speed)
            if not force and not state_changed:
                return
            self._last_speeds = (left_speed, right_speed)
            if state_changed:
                self._drive_state_sequence += 1

        LOGGER.debug(
            "Applying tank speeds left=%s right=%s reason=%s",
            left_speed,
            right_speed,
            reason,
        )
        self._motor_driver.setSpeeds(left_speed, right_speed)

    def _run_watchdog(self) -> None:
        while not self._stop_event.wait(self._watchdog_poll_interval):
            with self._lock:
                if self._closed:
                    return
                last_message_monotonic = self._last_message_monotonic

            if last_message_monotonic is None:
                continue

            if time.monotonic() - last_message_monotonic < self._watchdog_timeout_seconds:
                continue

            self.stop(
                reason=(
                    "cmd_vel watchdog timeout after "
                    f"{self._watchdog_timeout_seconds:.3f}s"
                ),
            )
