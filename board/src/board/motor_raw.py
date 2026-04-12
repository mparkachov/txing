from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from .motor_driver import (
    DEFAULT_DRIVE_GPIO_CHIP,
    DEFAULT_DRIVE_LEFT_DIR_GPIO,
    DEFAULT_DRIVE_LEFT_INVERTED,
    DEFAULT_DRIVE_LEFT_PWM_CHANNEL,
    DEFAULT_DRIVE_PWM_CHIP,
    DEFAULT_DRIVE_PWM_HZ,
    DEFAULT_DRIVE_RAW_MAX_SPEED,
    DEFAULT_DRIVE_RIGHT_DIR_GPIO,
    DEFAULT_DRIVE_RIGHT_INVERTED,
    DEFAULT_DRIVE_RIGHT_PWM_CHANNEL,
    Drv8835MotorDriver,
    DriveHardwareConfig,
    ENV_DRIVE_GPIO_CHIP,
    ENV_DRIVE_LEFT_DIR_GPIO,
    ENV_DRIVE_LEFT_INVERTED,
    ENV_DRIVE_LEFT_PWM_CHANNEL,
    ENV_DRIVE_PWM_CHIP,
    ENV_DRIVE_PWM_HZ,
    ENV_DRIVE_RAW_MAX_SPEED,
    ENV_DRIVE_RIGHT_DIR_GPIO,
    ENV_DRIVE_RIGHT_INVERTED,
    ENV_DRIVE_RIGHT_PWM_CHANNEL,
    parse_bool_text,
)

LOGGER = logging.getLogger("board.motor_raw")

DEFAULT_BOARD_SERVICE_NAME = "board"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as err:
        raise RuntimeError(f"invalid integer in ${name}: {raw!r}") from err


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return parse_bool_text(raw, option_name=f"${name}")


def _parse_bool_arg(value: str) -> bool:
    try:
        return parse_bool_text(value, option_name="boolean option")
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from err


def _configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply raw DRV8835 left/right speeds directly for board motor bring-up",
    )
    parser.add_argument("--left", type=int, required=True, help="Raw left speed in range [-max, max]")
    parser.add_argument("--right", type=int, required=True, help="Raw right speed in range [-max, max]")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional run duration in seconds; omit to hold until Ctrl-C",
    )
    parser.add_argument(
        "--skip-service-check",
        action="store_true",
        help="Skip `systemctl is-active board` safety check",
    )
    parser.add_argument(
        "--service-name",
        default=DEFAULT_BOARD_SERVICE_NAME,
        help="Systemd service name to guard against (default: board)",
    )
    parser.add_argument(
        "--drive-raw-max-speed",
        type=int,
        default=_env_int(ENV_DRIVE_RAW_MAX_SPEED, DEFAULT_DRIVE_RAW_MAX_SPEED),
        help=f"Raw motor max speed (default: ${ENV_DRIVE_RAW_MAX_SPEED} or {DEFAULT_DRIVE_RAW_MAX_SPEED})",
    )
    parser.add_argument(
        "--drive-pwm-hz",
        type=int,
        default=_env_int(ENV_DRIVE_PWM_HZ, DEFAULT_DRIVE_PWM_HZ),
        help=f"PWM frequency in Hz (default: ${ENV_DRIVE_PWM_HZ} or {DEFAULT_DRIVE_PWM_HZ})",
    )
    parser.add_argument(
        "--drive-pwm-chip",
        type=int,
        default=_env_int(ENV_DRIVE_PWM_CHIP, DEFAULT_DRIVE_PWM_CHIP),
        help=f"PWM chip index (default: ${ENV_DRIVE_PWM_CHIP} or {DEFAULT_DRIVE_PWM_CHIP})",
    )
    parser.add_argument(
        "--drive-left-pwm-channel",
        type=int,
        default=_env_int(ENV_DRIVE_LEFT_PWM_CHANNEL, DEFAULT_DRIVE_LEFT_PWM_CHANNEL),
        help=(
            f"Left motor PWM channel index "
            f"(default: ${ENV_DRIVE_LEFT_PWM_CHANNEL} or {DEFAULT_DRIVE_LEFT_PWM_CHANNEL})"
        ),
    )
    parser.add_argument(
        "--drive-right-pwm-channel",
        type=int,
        default=_env_int(ENV_DRIVE_RIGHT_PWM_CHANNEL, DEFAULT_DRIVE_RIGHT_PWM_CHANNEL),
        help=(
            f"Right motor PWM channel index "
            f"(default: ${ENV_DRIVE_RIGHT_PWM_CHANNEL} or {DEFAULT_DRIVE_RIGHT_PWM_CHANNEL})"
        ),
    )
    parser.add_argument(
        "--drive-gpio-chip",
        type=int,
        default=_env_int(ENV_DRIVE_GPIO_CHIP, DEFAULT_DRIVE_GPIO_CHIP),
        help=f"GPIO chip index for lgpio (default: ${ENV_DRIVE_GPIO_CHIP} or {DEFAULT_DRIVE_GPIO_CHIP})",
    )
    parser.add_argument(
        "--drive-left-dir-gpio",
        type=int,
        default=_env_int(ENV_DRIVE_LEFT_DIR_GPIO, DEFAULT_DRIVE_LEFT_DIR_GPIO),
        help=(
            f"Left direction GPIO pin (BCM numbering) "
            f"(default: ${ENV_DRIVE_LEFT_DIR_GPIO} or {DEFAULT_DRIVE_LEFT_DIR_GPIO})"
        ),
    )
    parser.add_argument(
        "--drive-right-dir-gpio",
        type=int,
        default=_env_int(ENV_DRIVE_RIGHT_DIR_GPIO, DEFAULT_DRIVE_RIGHT_DIR_GPIO),
        help=(
            f"Right direction GPIO pin (BCM numbering) "
            f"(default: ${ENV_DRIVE_RIGHT_DIR_GPIO} or {DEFAULT_DRIVE_RIGHT_DIR_GPIO})"
        ),
    )
    parser.add_argument(
        "--drive-left-inverted",
        type=_parse_bool_arg,
        default=_env_bool(ENV_DRIVE_LEFT_INVERTED, DEFAULT_DRIVE_LEFT_INVERTED),
        help=(
            f"Whether to invert left motor direction "
            f"(default: ${ENV_DRIVE_LEFT_INVERTED} or {str(DEFAULT_DRIVE_LEFT_INVERTED).lower()})"
        ),
    )
    parser.add_argument(
        "--drive-right-inverted",
        type=_parse_bool_arg,
        default=_env_bool(ENV_DRIVE_RIGHT_INVERTED, DEFAULT_DRIVE_RIGHT_INVERTED),
        help=(
            f"Whether to invert right motor direction "
            f"(default: ${ENV_DRIVE_RIGHT_INVERTED} or {str(DEFAULT_DRIVE_RIGHT_INVERTED).lower()})"
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def _ensure_board_service_not_running(service_name: str) -> None:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        LOGGER.warning("systemctl is unavailable; skipping service activity check")
        return
    if result.returncode == 0:
        raise RuntimeError(
            f"service {service_name!r} is active; stop it before running raw motor tests"
        )


def _build_hardware_config(args: argparse.Namespace) -> DriveHardwareConfig:
    return DriveHardwareConfig(
        raw_max_speed=args.drive_raw_max_speed,
        pwm_hz=args.drive_pwm_hz,
        pwm_chip=args.drive_pwm_chip,
        left_pwm_channel=args.drive_left_pwm_channel,
        right_pwm_channel=args.drive_right_pwm_channel,
        gpio_chip=args.drive_gpio_chip,
        left_dir_gpio=args.drive_left_dir_gpio,
        right_dir_gpio=args.drive_right_dir_gpio,
        left_inverted=args.drive_left_inverted,
        right_inverted=args.drive_right_inverted,
        pwm_sysfs_root=Path("/sys/class/pwm"),
    )


def main() -> None:
    args = _parse_args()
    _configure_logging(args.debug)

    stop_event = threading.Event()

    def _request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    try:
        if args.duration is not None and args.duration <= 0:
            raise RuntimeError("--duration must be greater than 0")
        config = _build_hardware_config(args)
        if abs(args.left) > config.raw_max_speed:
            raise RuntimeError(
                f"--left must be in range [-{config.raw_max_speed}, {config.raw_max_speed}]"
            )
        if abs(args.right) > config.raw_max_speed:
            raise RuntimeError(
                f"--right must be in range [-{config.raw_max_speed}, {config.raw_max_speed}]"
            )
        left = args.left
        right = args.right
        if not args.skip_service_check:
            _ensure_board_service_not_running(args.service_name)
    except (RuntimeError, ValueError) as err:
        print(f"board-motor-raw start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    driver: Drv8835MotorDriver | None = None
    try:
        driver = Drv8835MotorDriver(config=config)
        driver.setSpeeds(left, right)
        LOGGER.info(
            "Applied raw DRV8835 speeds left=%s right=%s max=%s",
            left,
            right,
            config.raw_max_speed,
        )

        if args.duration is None:
            LOGGER.info("Holding speeds until Ctrl-C")
            while not stop_event.wait(0.5):
                pass
        else:
            LOGGER.info("Holding speeds for %.3fs", args.duration)
            stop_event.wait(args.duration)
    except RuntimeError as err:
        print(f"board-motor-raw failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
    finally:
        if driver is not None:
            driver.close()
            LOGGER.info("Motors stopped")


if __name__ == "__main__":
    main()
