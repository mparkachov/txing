from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any, Callable

LOGGER = logging.getLogger("board.motor_driver")

DEFAULT_DRIVE_RAW_MAX_SPEED = 480
DEFAULT_DRIVE_PWM_HZ = 20_000
DEFAULT_DRIVE_PWM_CHIP = 0
DEFAULT_DRIVE_LEFT_PWM_CHANNEL = 0
DEFAULT_DRIVE_RIGHT_PWM_CHANNEL = 1
DEFAULT_DRIVE_GPIO_CHIP = 0
DEFAULT_DRIVE_LEFT_DIR_GPIO = 5
DEFAULT_DRIVE_RIGHT_DIR_GPIO = 6
DEFAULT_DRIVE_LEFT_INVERTED = False
DEFAULT_DRIVE_RIGHT_INVERTED = False
DEFAULT_DRIVE_PERCENT_MAX_SPEED = 100
DEFAULT_PWM_SYSFS_ROOT = Path("/sys/class/pwm")

ENV_DRIVE_RAW_MAX_SPEED = "BOARD_DRIVE_RAW_MAX_SPEED"
ENV_DRIVE_PWM_HZ = "BOARD_DRIVE_PWM_HZ"
ENV_DRIVE_PWM_CHIP = "BOARD_DRIVE_PWM_CHIP"
ENV_DRIVE_LEFT_PWM_CHANNEL = "BOARD_DRIVE_LEFT_PWM_CHANNEL"
ENV_DRIVE_RIGHT_PWM_CHANNEL = "BOARD_DRIVE_RIGHT_PWM_CHANNEL"
ENV_DRIVE_GPIO_CHIP = "BOARD_DRIVE_GPIO_CHIP"
ENV_DRIVE_LEFT_DIR_GPIO = "BOARD_DRIVE_LEFT_DIR_GPIO"
ENV_DRIVE_RIGHT_DIR_GPIO = "BOARD_DRIVE_RIGHT_DIR_GPIO"
ENV_DRIVE_LEFT_INVERTED = "BOARD_DRIVE_LEFT_INVERTED"
ENV_DRIVE_RIGHT_INVERTED = "BOARD_DRIVE_RIGHT_INVERTED"


@dataclass(frozen=True)
class DriveHardwareConfig:
    raw_max_speed: int = DEFAULT_DRIVE_RAW_MAX_SPEED
    pwm_hz: int = DEFAULT_DRIVE_PWM_HZ
    pwm_chip: int = DEFAULT_DRIVE_PWM_CHIP
    left_pwm_channel: int = DEFAULT_DRIVE_LEFT_PWM_CHANNEL
    right_pwm_channel: int = DEFAULT_DRIVE_RIGHT_PWM_CHANNEL
    gpio_chip: int = DEFAULT_DRIVE_GPIO_CHIP
    left_dir_gpio: int = DEFAULT_DRIVE_LEFT_DIR_GPIO
    right_dir_gpio: int = DEFAULT_DRIVE_RIGHT_DIR_GPIO
    left_inverted: bool = DEFAULT_DRIVE_LEFT_INVERTED
    right_inverted: bool = DEFAULT_DRIVE_RIGHT_INVERTED
    pwm_sysfs_root: Path = DEFAULT_PWM_SYSFS_ROOT

    def __post_init__(self) -> None:
        if self.raw_max_speed <= 0:
            raise ValueError("raw_max_speed must be positive")
        if self.pwm_hz <= 0:
            raise ValueError("pwm_hz must be positive")
        for name, value in (
            ("pwm_chip", self.pwm_chip),
            ("left_pwm_channel", self.left_pwm_channel),
            ("right_pwm_channel", self.right_pwm_channel),
            ("gpio_chip", self.gpio_chip),
            ("left_dir_gpio", self.left_dir_gpio),
            ("right_dir_gpio", self.right_dir_gpio),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.left_pwm_channel == self.right_pwm_channel:
            raise ValueError("left and right PWM channels must differ")
        if self.left_dir_gpio == self.right_dir_gpio:
            raise ValueError("left and right direction GPIO pins must differ")


def parse_bool_text(value: str, *, option_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{option_name} expects one of: true/false, 1/0, yes/no, on/off")


def clamp_speed(value: int, max_speed: int) -> int:
    if max_speed <= 0:
        raise ValueError("max_speed must be positive")
    return max(-max_speed, min(max_speed, value))


def scale_speed(value: int, *, source_max_speed: int, target_max_speed: int) -> int:
    if source_max_speed <= 0:
        raise ValueError("source_max_speed must be positive")
    if target_max_speed <= 0:
        raise ValueError("target_max_speed must be positive")
    clamped = clamp_speed(value, source_max_speed)
    return int(round((clamped / source_max_speed) * target_max_speed))


class _SysfsPwmChannel:
    def __init__(
        self,
        *,
        pwm_sysfs_root: Path,
        chip: int,
        channel: int,
        frequency_hz: int,
        on_export: Callable[[Path, int], None] | None = None,
    ) -> None:
        self._chip_path = pwm_sysfs_root / f"pwmchip{chip}"
        self._channel = channel
        self._channel_path = self._chip_path / f"pwm{channel}"
        self._owns_channel = False
        self._period_ns = int(round(1_000_000_000 / frequency_hz))
        if not self._chip_path.is_dir():
            raise RuntimeError(f"PWM chip path does not exist: {self._chip_path}")

        if not self._channel_path.is_dir():
            self._write_int(self._chip_path / "export", channel)
            self._owns_channel = True
            if on_export is not None:
                on_export(self._chip_path, channel)
            self._wait_for_path(self._channel_path, timeout_seconds=1.0)

        self._enable_path = self._channel_path / "enable"
        self._period_path = self._channel_path / "period"
        self._duty_path = self._channel_path / "duty_cycle"
        self._disable()
        self._write_int(self._period_path, self._period_ns)
        self._write_int(self._duty_path, 0)
        self._enable()

    @property
    def period_ns(self) -> int:
        return self._period_ns

    def set_duty_cycle_ns(self, duty_cycle_ns: int) -> None:
        clamped = max(0, min(self._period_ns, duty_cycle_ns))
        self._write_int(self._duty_path, clamped)

    def close(self) -> None:
        self._disable()
        self._write_int(self._duty_path, 0, tolerate_errors=True)
        if self._owns_channel:
            self._write_int(self._chip_path / "unexport", self._channel, tolerate_errors=True)

    def _enable(self) -> None:
        self._write_int(self._enable_path, 1)

    def _disable(self) -> None:
        self._write_int(self._enable_path, 0, tolerate_errors=True)

    def _wait_for_path(self, path: Path, *, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if path.is_dir():
                return
            time.sleep(0.01)
        raise RuntimeError(f"PWM channel path did not appear after export: {path}")

    def _write_int(self, path: Path, value: int, *, tolerate_errors: bool = False) -> None:
        try:
            path.write_text(f"{value}\n", encoding="utf-8")
        except OSError as err:
            if tolerate_errors:
                return
            raise RuntimeError(f"failed to write PWM sysfs value to {path}: {err}") from err


@dataclass(frozen=True)
class _HardwareResources:
    left_pwm: _SysfsPwmChannel
    right_pwm: _SysfsPwmChannel
    left_direction: Any
    right_direction: Any
    pin_factory: Any


class Drv8835MotorDriver:
    def __init__(
        self,
        *,
        config: DriveHardwareConfig,
        resources: _HardwareResources | None = None,
        pwm_on_export: Callable[[Path, int], None] | None = None,
    ) -> None:
        self._config = config
        self.MAX_SPEED = config.raw_max_speed
        self._closed = False
        self._resources = (
            resources
            if resources is not None
            else self._create_hardware_resources(config=config, pwm_on_export=pwm_on_export)
        )
        self.setSpeeds(0, 0)

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        if self._closed:
            return
        left_speed = clamp_speed(int(m1_speed), self.MAX_SPEED)
        right_speed = clamp_speed(int(m2_speed), self.MAX_SPEED)
        try:
            self._apply_side(
                speed=left_speed,
                pwm=self._resources.left_pwm,
                direction=self._resources.left_direction,
                inverted=self._config.left_inverted,
            )
            self._apply_side(
                speed=right_speed,
                pwm=self._resources.right_pwm,
                direction=self._resources.right_direction,
                inverted=self._config.right_inverted,
            )
        except Exception as err:
            self._force_stop_quietly()
            raise RuntimeError(f"failed to apply DRV8835 speeds: {err}") from err

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._force_stop_quietly()
        self._resources.left_direction.close()
        self._resources.right_direction.close()
        self._resources.left_pwm.close()
        self._resources.right_pwm.close()
        if self._resources.pin_factory is not None:
            self._resources.pin_factory.close()

    def _apply_side(
        self,
        *,
        speed: int,
        pwm: _SysfsPwmChannel,
        direction: Any,
        inverted: bool,
    ) -> None:
        effective_speed = -speed if inverted else speed
        direction_high = effective_speed < 0
        if direction_high:
            direction.on()
        else:
            direction.off()
        duty_cycle = int(round((abs(effective_speed) / self.MAX_SPEED) * pwm.period_ns))
        pwm.set_duty_cycle_ns(duty_cycle)

    def _force_stop_quietly(self) -> None:
        try:
            self._resources.left_direction.off()
            self._resources.right_direction.off()
            self._resources.left_pwm.set_duty_cycle_ns(0)
            self._resources.right_pwm.set_duty_cycle_ns(0)
        except Exception:
            pass

    @staticmethod
    def _create_hardware_resources(
        *,
        config: DriveHardwareConfig,
        pwm_on_export: Callable[[Path, int], None] | None,
    ) -> _HardwareResources:
        left_pwm: _SysfsPwmChannel | None = None
        right_pwm: _SysfsPwmChannel | None = None
        left_direction: Any | None = None
        right_direction: Any | None = None
        pin_factory: Any | None = None
        try:
            left_pwm = _SysfsPwmChannel(
                pwm_sysfs_root=config.pwm_sysfs_root,
                chip=config.pwm_chip,
                channel=config.left_pwm_channel,
                frequency_hz=config.pwm_hz,
                on_export=pwm_on_export,
            )
            right_pwm = _SysfsPwmChannel(
                pwm_sysfs_root=config.pwm_sysfs_root,
                chip=config.pwm_chip,
                channel=config.right_pwm_channel,
                frequency_hz=config.pwm_hz,
                on_export=pwm_on_export,
            )

            from gpiozero import OutputDevice
            from gpiozero.pins.lgpio import LGPIOFactory

            pin_factory = LGPIOFactory(chip=config.gpio_chip)
            left_direction = OutputDevice(
                config.left_dir_gpio,
                pin_factory=pin_factory,
                initial_value=False,
            )
            right_direction = OutputDevice(
                config.right_dir_gpio,
                pin_factory=pin_factory,
                initial_value=False,
            )
            return _HardwareResources(
                left_pwm=left_pwm,
                right_pwm=right_pwm,
                left_direction=left_direction,
                right_direction=right_direction,
                pin_factory=pin_factory,
            )
        except Exception as err:
            for resource in (left_direction, right_direction, left_pwm, right_pwm, pin_factory):
                try:
                    if resource is not None:
                        resource.close()
                except Exception:
                    pass
            raise RuntimeError(
                "failed to initialize DRV8835 motor hardware; "
                "check root permissions, PWM overlay, and GPIO availability"
            ) from err


class PercentMotorDriverAdapter:
    def __init__(
        self,
        *,
        raw_motor_driver: Any,
        percent_max_speed: int = DEFAULT_DRIVE_PERCENT_MAX_SPEED,
        raw_max_speed: int = DEFAULT_DRIVE_RAW_MAX_SPEED,
    ) -> None:
        if percent_max_speed <= 0:
            raise ValueError("percent_max_speed must be positive")
        if raw_max_speed <= 0:
            raise ValueError("raw_max_speed must be positive")
        self._raw_motor_driver = raw_motor_driver
        self._percent_max_speed = percent_max_speed
        self._raw_max_speed = raw_max_speed
        self.MAX_SPEED = percent_max_speed

    def setSpeeds(self, m1_speed: int, m2_speed: int) -> None:
        left_raw = scale_speed(
            int(m1_speed),
            source_max_speed=self._percent_max_speed,
            target_max_speed=self._raw_max_speed,
        )
        right_raw = scale_speed(
            int(m2_speed),
            source_max_speed=self._percent_max_speed,
            target_max_speed=self._raw_max_speed,
        )
        self._raw_motor_driver.setSpeeds(left_raw, right_raw)

    def close(self) -> None:
        close_method = getattr(self._raw_motor_driver, "close", None)
        if callable(close_method):
            close_method()
