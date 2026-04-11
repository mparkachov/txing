from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from aws.auth import AwsCredentialSnapshot, ensure_aws_profile, freeze_session_credentials

from .video_state import (
    DEFAULT_VIDEO_CHANNEL_NAME,
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_STATE_FILE,
    VIDEO_STATUS_ERROR,
    VIDEO_STATUS_READY,
    VIDEO_STATUS_STARTING,
    VIDEO_TRANSPORT,
    load_video_state,
)

DEFAULT_ASSUME_READY_AFTER_SECONDS = 3.0
DEFAULT_REGION_ENV = "BOARD_VIDEO_REGION"
DEFAULT_CHANNEL_NAME_ENV = "BOARD_VIDEO_CHANNEL_NAME"
DEFAULT_SENDER_COMMAND_ENV = "BOARD_VIDEO_SENDER_COMMAND"
DEFAULT_READY_PATTERN_ENV = "BOARD_VIDEO_READY_PATTERN"
DEFAULT_VIEWER_CONNECTED_PATTERN_ENV = "BOARD_VIDEO_VIEWER_CONNECTED_PATTERN"
DEFAULT_VIEWER_DISCONNECTED_PATTERN_ENV = "BOARD_VIDEO_VIEWER_DISCONNECTED_PATTERN"
DEFAULT_AWS_SHARED_CREDENTIALS_FILE_ENV = "AWS_SHARED_CREDENTIALS_FILE"
DEFAULT_AWS_CONFIG_FILE_ENV = "AWS_CONFIG_FILE"
DEFAULT_SSL_CERT_FILE_ENV = "SSL_CERT_FILE"
DEFAULT_KVS_CA_CERT_PATH_ENV = "AWS_KVS_CACERT_PATH"
LEGACY_REGION_ENV = "TXING_BOARD_VIDEO_REGION"
LEGACY_CHANNEL_NAME_ENV = "TXING_BOARD_VIDEO_CHANNEL_NAME"
LEGACY_SENDER_COMMAND_ENV = "TXING_BOARD_VIDEO_SENDER_COMMAND"
LEGACY_READY_PATTERN_ENV = "TXING_BOARD_VIDEO_READY_PATTERN"
LEGACY_VIEWER_CONNECTED_PATTERN_ENV = "TXING_BOARD_VIDEO_VIEWER_CONNECTED_PATTERN"
LEGACY_VIEWER_DISCONNECTED_PATTERN_ENV = "TXING_BOARD_VIDEO_VIEWER_DISCONNECTED_PATTERN"
DEFAULT_READY_PATTERN = r"^TXING_KVS_READY(?:\s|$)"
DEFAULT_VIEWER_CONNECTED_PATTERN = r"^TXING_VIEWER_CONNECTED(?:\s|$)"
DEFAULT_VIEWER_DISCONNECTED_PATTERN = r"^TXING_VIEWER_DISCONNECTED(?:\s|$)"
LOGGER = logging.getLogger("board.video_sender")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_state(
    *,
    status: str,
    ready: bool,
    viewer_url: str,
    channel_name: str,
    viewer_connected: bool,
    last_error: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "ready": ready,
        "transport": VIDEO_TRANSPORT,
        "session": {
            "viewerUrl": viewer_url,
            "channelName": channel_name,
        },
        "codec": {
            "video": DEFAULT_VIDEO_CODEC,
        },
        "viewerConnected": viewer_connected,
        "lastError": last_error,
        "updatedAt": _utc_now(),
    }


def _write_state_file(state_file: Path, payload: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_file.with_suffix(f"{state_file.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(state_file)


def _resolve_channel_arn(*, region: str, channel_name: str) -> str:
    try:
        client = boto3.client("kinesisvideo", region_name=region)
        response = client.describe_signaling_channel(ChannelName=channel_name)
        channel_info = response.get("ChannelInfo") or {}
        channel_arn = channel_info.get("ChannelARN")
        if not isinstance(channel_arn, str) or not channel_arn.strip():
            raise RuntimeError(f"AWS did not return a signaling channel ARN for {channel_name!r}")

        channel_status = channel_info.get("ChannelStatus")
        if channel_status not in ("ACTIVE", "UPDATING"):
            raise RuntimeError(
                f"signaling channel {channel_name!r} is not ready (status={channel_status!r})"
            )
        return channel_arn
    except RuntimeError:
        raise
    except Exception as err:
        raise RuntimeError(
            f"failed to describe signaling channel {channel_name!r} in region {region!r}: {err}"
        ) from err


def _resolve_final_credentials() -> AwsCredentialSnapshot:
    try:
        session = boto3.session.Session()
        return freeze_session_credentials(session)
    except Exception as err:
        raise RuntimeError(f"failed to resolve AWS credentials for board video sender: {err}") from err


def _compile_pattern(value: str, *, env_name: str) -> re.Pattern[str] | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return re.compile(stripped)
    except re.error as err:
        raise RuntimeError(f"{env_name} is not a valid regular expression: {err}") from err


def _env_value(environment: dict[str, str], *names: str) -> str:
    for name in names:
        value = environment.get(name, "").strip()
        if value:
            return value
    return ""


def _optional_env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    return None


def _build_sender_environment(
    *,
    region: str,
    channel_name: str,
    credentials: AwsCredentialSnapshot,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment[DEFAULT_REGION_ENV] = region
    environment[DEFAULT_CHANNEL_NAME_ENV] = channel_name
    environment["AWS_ACCESS_KEY_ID"] = credentials.access_key_id
    environment["AWS_SECRET_ACCESS_KEY"] = credentials.secret_access_key
    if credentials.session_token:
        environment["AWS_SESSION_TOKEN"] = credentials.session_token
    else:
        environment.pop("AWS_SESSION_TOKEN", None)
    environment.pop("AWS_PROFILE", None)
    environment.pop("AWS_DEFAULT_PROFILE", None)
    environment.pop(DEFAULT_AWS_SHARED_CREDENTIALS_FILE_ENV, None)
    environment.pop(DEFAULT_AWS_CONFIG_FILE_ENV, None)
    environment.pop(DEFAULT_SSL_CERT_FILE_ENV, None)
    environment.pop(DEFAULT_KVS_CA_CERT_PATH_ENV, None)
    environment.pop("BOARD_VIDEO_CA_FILE", None)
    environment.pop("TXING_BOARD_VIDEO_CA_FILE", None)
    return environment


@dataclass(frozen=True)
class VideoSenderRuntimeConfig:
    region: str
    channel_name: str
    viewer_url: str
    state_file: Path
    sender_command: str
    assume_ready_after_seconds: float
    ready_pattern: re.Pattern[str] | None
    viewer_connected_pattern: re.Pattern[str] | None
    viewer_disconnected_pattern: re.Pattern[str] | None


class VideoSenderProcess:
    def __init__(self, config: VideoSenderRuntimeConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[str] | None = None
        self._stop_requested = threading.Event()
        self._state_lock = threading.Lock()
        self._viewer_connected = False
        self._ready = False

    def run(self) -> int:
        LOGGER.info(
            "Board video sender starting pid=%s region=%s channel_name=%s state_file=%s",
            os.getpid(),
            self._config.region,
            self._config.channel_name,
            self._config.state_file,
        )
        _write_state_file(
            self._config.state_file,
            _build_state(
                status=VIDEO_STATUS_STARTING,
                ready=False,
                viewer_url=self._config.viewer_url,
                channel_name=self._config.channel_name,
                viewer_connected=False,
                last_error=None,
            ),
        )

        LOGGER.info(
            "Resolving signaling channel region=%s channel_name=%s",
            self._config.region,
            self._config.channel_name,
        )
        _resolve_channel_arn(
            region=self._config.region,
            channel_name=self._config.channel_name,
        )
        LOGGER.info(
            "Resolved signaling channel region=%s channel_name=%s",
            self._config.region,
            self._config.channel_name,
        )
        credentials = _resolve_final_credentials()
        command = shlex.split(self._config.sender_command)
        if not command:
            raise RuntimeError(f"{DEFAULT_SENDER_COMMAND_ENV} must not be empty")

        LOGGER.info(
            "Launching native video sender command=%s",
            self._config.sender_command,
        )
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_build_sender_environment(
                region=self._config.region,
                channel_name=self._config.channel_name,
                credentials=credentials,
            ),
        )
        LOGGER.info(
            "Native video sender started pid=%s",
            self._process.pid,
        )
        reader_thread = threading.Thread(
            target=self._forward_sender_output,
            name="txing-board-video-sender-output",
            daemon=True,
        )
        reader_thread.start()

        ready_deadline = time.monotonic() + self._config.assume_ready_after_seconds
        while not self._stop_requested.is_set():
            process = self._process
            if process is None:
                raise RuntimeError("video sender process was not started")

            return_code = process.poll()
            if return_code is not None:
                LOGGER.error(
                    "Native video sender exited before readiness pid=%s return_code=%s",
                    process.pid,
                    return_code,
                )
                raise RuntimeError(f"video sender command exited with code {return_code}")

            if not self._ready:
                if (
                    self._config.ready_pattern is None
                    and time.monotonic() >= ready_deadline
                ):
                    self._set_ready()
            time.sleep(0.2)

        self._terminate_child()
        return 0

    def request_stop(self) -> None:
        self._stop_requested.set()

    def _forward_sender_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if line:
                print(f"[txing-board-video-sender] {line}", flush=True)
            self._handle_output_line(line)

    def _handle_output_line(self, line: str) -> None:
        if self._config.ready_pattern and self._config.ready_pattern.search(line):
            self._set_ready()
        if (
            self._config.viewer_connected_pattern
            and self._config.viewer_connected_pattern.search(line)
        ):
            self._set_viewer_connected(True)
        if (
            self._config.viewer_disconnected_pattern
            and self._config.viewer_disconnected_pattern.search(line)
        ):
            self._set_viewer_connected(False)

    def _set_ready(self) -> None:
        with self._state_lock:
            if self._ready:
                return
            self._ready = True
            viewer_connected = self._viewer_connected

        LOGGER.info(
            "Board video sender ready viewer_connected=%s",
            viewer_connected,
        )
        _write_state_file(
            self._config.state_file,
            _build_state(
                status=VIDEO_STATUS_READY,
                ready=True,
                viewer_url=self._config.viewer_url,
                channel_name=self._config.channel_name,
                viewer_connected=viewer_connected,
                last_error=None,
            ),
        )

    def _set_viewer_connected(self, connected: bool) -> None:
        with self._state_lock:
            self._viewer_connected = connected
            ready = self._ready

        LOGGER.info(
            "Board video viewer connection changed connected=%s ready=%s",
            connected,
            ready,
        )
        _write_state_file(
            self._config.state_file,
            _build_state(
                status=VIDEO_STATUS_READY if ready else VIDEO_STATUS_STARTING,
                ready=ready,
                viewer_url=self._config.viewer_url,
                channel_name=self._config.channel_name,
                viewer_connected=connected,
                last_error=None,
            ),
        )

    def _terminate_child(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)


class VideoSenderSupervisor:
    def __init__(
        self,
        *,
        channel_name: str,
        viewer_url: str,
        region: str,
        sender_command: str,
        aws_shared_credentials_file: Path | None = None,
        aws_config_file: Path | None = None,
        state_file: Path = DEFAULT_VIDEO_STATE_FILE,
    ) -> None:
        self._channel_name = channel_name
        self._viewer_url = viewer_url
        self._region = region
        self._sender_command = sender_command
        self._aws_shared_credentials_file = aws_shared_credentials_file
        self._aws_config_file = aws_config_file
        self._state_file = state_file
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def state_file(self) -> Path:
        return self._state_file

    @property
    def pid(self) -> int | None:
        if self._process is None:
            return None
        return self._process.pid

    def start(self) -> None:
        if self.is_running():
            return
        command = [
            sys.executable,
            "-m",
            "board.video_sender",
            "--region",
            self._region,
            "--channel-name",
            self._channel_name,
            "--viewer-url",
            self._viewer_url,
            "--state-file",
            str(self._state_file),
            "--sender-command",
            self._sender_command,
        ]
        if self._aws_shared_credentials_file is not None:
            command.extend(
                [
                    "--aws-shared-credentials-file",
                    str(self._aws_shared_credentials_file),
                ]
            )
        if self._aws_config_file is not None:
            command.extend(["--aws-config-file", str(self._aws_config_file)])
        self._process = subprocess.Popen(command)

    def ensure_running(self) -> None:
        if not self.is_running():
            self.start()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def return_code(self) -> int | None:
        if self._process is None:
            return None
        return self._process.poll()

    def read_state(self) -> dict[str, Any]:
        return load_video_state(
            self._state_file,
            viewer_url=self._viewer_url,
            channel_name=self._channel_name,
        )

    def stop(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dedicated board video sender state manager for txing",
    )
    parser.add_argument("--region", required=True, help="AWS region for the signaling channel")
    parser.add_argument(
        "--channel-name",
        default=DEFAULT_VIDEO_CHANNEL_NAME,
        help=f"AWS KVS signaling channel name (default: {DEFAULT_VIDEO_CHANNEL_NAME})",
    )
    parser.add_argument(
        "--viewer-url",
        required=True,
        help="Operator-facing browser URL for the board video route",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_VIDEO_STATE_FILE,
        help=f"Path to the local sender state file (default: {DEFAULT_VIDEO_STATE_FILE})",
    )
    parser.add_argument(
        "--sender-command",
        default=_env_value(os.environ, DEFAULT_SENDER_COMMAND_ENV, LEGACY_SENDER_COMMAND_ENV),
        help=(
            "Command that runs the actual KVS master sender "
            f"(default: ${DEFAULT_SENDER_COMMAND_ENV})"
        ),
    )
    parser.add_argument(
        "--aws-shared-credentials-file",
        type=Path,
        default=_optional_env_path(DEFAULT_AWS_SHARED_CREDENTIALS_FILE_ENV),
        help=(
            "AWS shared credentials file used for the signaling-channel lookup before "
            "final credential injection into the native sender "
            f"(default: ${DEFAULT_AWS_SHARED_CREDENTIALS_FILE_ENV})"
        ),
    )
    parser.add_argument(
        "--aws-config-file",
        type=Path,
        default=_optional_env_path(DEFAULT_AWS_CONFIG_FILE_ENV),
        help=(
            "AWS config file used for the signaling-channel lookup before final "
            f"credential injection into the native sender (default: ${DEFAULT_AWS_CONFIG_FILE_ENV})"
        ),
    )
    parser.add_argument(
        "--assume-ready-after-seconds",
        type=float,
        default=DEFAULT_ASSUME_READY_AFTER_SECONDS,
        help=(
            "Fallback startup grace period before marking the sender ready when no "
            "ready-pattern is configured"
        ),
    )
    parser.add_argument(
        "--ready-pattern",
        default=(
            _env_value(os.environ, DEFAULT_READY_PATTERN_ENV, LEGACY_READY_PATTERN_ENV)
            or DEFAULT_READY_PATTERN
        ),
        help=f"Regex for child output that confirms sender readiness (default: ${DEFAULT_READY_PATTERN_ENV})",
    )
    parser.add_argument(
        "--viewer-connected-pattern",
        default=(
            _env_value(
                os.environ,
                DEFAULT_VIEWER_CONNECTED_PATTERN_ENV,
                LEGACY_VIEWER_CONNECTED_PATTERN_ENV,
            )
            or DEFAULT_VIEWER_CONNECTED_PATTERN
        ),
        help=(
            "Regex for child output that indicates a viewer is connected "
            f"(default: ${DEFAULT_VIEWER_CONNECTED_PATTERN_ENV})"
        ),
    )
    parser.add_argument(
        "--viewer-disconnected-pattern",
        default=(
            _env_value(
                os.environ,
                DEFAULT_VIEWER_DISCONNECTED_PATTERN_ENV,
                LEGACY_VIEWER_DISCONNECTED_PATTERN_ENV,
            )
            or DEFAULT_VIEWER_DISCONNECTED_PATTERN
        ),
        help=(
            "Regex for child output that indicates the viewer disconnected "
            f"(default: ${DEFAULT_VIEWER_DISCONNECTED_PATTERN_ENV})"
        ),
    )
    return parser.parse_args()


def main() -> None:
    _configure_logging()
    args = _parse_args()
    if args.aws_shared_credentials_file is not None:
        os.environ[DEFAULT_AWS_SHARED_CREDENTIALS_FILE_ENV] = str(args.aws_shared_credentials_file)
    if args.aws_config_file is not None:
        os.environ[DEFAULT_AWS_CONFIG_FILE_ENV] = str(args.aws_config_file)
    ensure_aws_profile("AWS_TXING_PROFILE")
    runtime = VideoSenderProcess(
        VideoSenderRuntimeConfig(
            region=args.region,
            channel_name=args.channel_name,
            viewer_url=args.viewer_url,
            state_file=args.state_file,
            sender_command=args.sender_command,
            assume_ready_after_seconds=args.assume_ready_after_seconds,
            ready_pattern=_compile_pattern(
                args.ready_pattern,
                env_name=DEFAULT_READY_PATTERN_ENV,
            ),
            viewer_connected_pattern=_compile_pattern(
                args.viewer_connected_pattern,
                env_name=DEFAULT_VIEWER_CONNECTED_PATTERN_ENV,
            ),
            viewer_disconnected_pattern=_compile_pattern(
                args.viewer_disconnected_pattern,
                env_name=DEFAULT_VIEWER_DISCONNECTED_PATTERN_ENV,
            ),
        )
    )

    def _request_stop(_signum: int, _frame: Any) -> None:
        runtime.request_stop()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    try:
        raise SystemExit(runtime.run())
    except Exception as err:
        _write_state_file(
            args.state_file,
            _build_state(
                status=VIDEO_STATUS_ERROR,
                ready=False,
                viewer_url=args.viewer_url,
                channel_name=args.channel_name,
                viewer_connected=False,
                last_error=str(err),
            ),
        )
        print(f"board video sender failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err


if __name__ == "__main__":
    main()
