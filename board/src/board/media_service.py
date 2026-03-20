from __future__ import annotations

import argparse
import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .media_state import (
    DEFAULT_MEDIA_STATE_FILE,
    DEFAULT_SIGNALLING_PORT,
    DEFAULT_STREAM_NAME,
    DEFAULT_VIDEO_CODEC,
    MEDIA_STATUS_ERROR,
    MEDIA_STATUS_READY,
    MEDIA_STATUS_STARTING,
    media_state_timestamp,
    save_media_state,
)
from .shadow_control import _detect_default_route_addresses

LOGGER = logging.getLogger("board.media_service")

DEFAULT_GST_LAUNCH_BIN = "gst-launch-1.0"
DEFAULT_RESTART_DELAY = 5.0
DEFAULT_STATE_WRITE_INTERVAL = 5.0
DEFAULT_STARTUP_GRACE_SECONDS = 2.0
DEFAULT_SIGNALLING_HOST = "::"
DEFAULT_SOURCE_PIPELINE = (
    "libcamerasrc "
    "! capsfilter caps=video/x-raw,width=1920,height=1080,framerate=30/1,format=NV12,interlace-mode=progressive "
    '! v4l2h264enc extra-controls="controls,repeat_sequence_header=1" '
    "! h264parse config-interval=-1"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Txing board-local GStreamer rswebrtc media service",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_MEDIA_STATE_FILE,
        help=f"Path to runtime media state file (default: {DEFAULT_MEDIA_STATE_FILE})",
    )
    parser.add_argument(
        "--stream-name",
        default=DEFAULT_STREAM_NAME,
        help=f"Published rswebrtc stream name (default: {DEFAULT_STREAM_NAME})",
    )
    parser.add_argument(
        "--signalling-port",
        type=int,
        default=DEFAULT_SIGNALLING_PORT,
        help=f"Published rswebrtc signalling port (default: {DEFAULT_SIGNALLING_PORT})",
    )
    parser.add_argument(
        "--signalling-host",
        default=DEFAULT_SIGNALLING_HOST,
        help=f"webrtcsink signalling server listen address (default: {DEFAULT_SIGNALLING_HOST})",
    )
    parser.add_argument(
        "--gst-launch-bin",
        default=DEFAULT_GST_LAUNCH_BIN,
        help=f"gst-launch executable to run (default: {DEFAULT_GST_LAUNCH_BIN})",
    )
    parser.add_argument(
        "--source-pipeline",
        default=DEFAULT_SOURCE_PIPELINE,
        help="GStreamer source fragment ending in H.264 before webrtcsink",
    )
    parser.add_argument(
        "--restart-delay",
        type=float,
        default=DEFAULT_RESTART_DELAY,
        help=f"Seconds to wait before restarting the media pipeline (default: {DEFAULT_RESTART_DELAY})",
    )
    parser.add_argument(
        "--state-write-interval",
        type=float,
        default=DEFAULT_STATE_WRITE_INTERVAL,
        help=f"Seconds between refreshed runtime state writes (default: {DEFAULT_STATE_WRITE_INTERVAL})",
    )
    parser.add_argument(
        "--startup-grace-seconds",
        type=float,
        default=DEFAULT_STARTUP_GRACE_SECONDS,
        help=f"Seconds before a running pipeline is marked ready (default: {DEFAULT_STARTUP_GRACE_SECONDS})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def _configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)


def _wait_for_stop(stop_event: threading.Event, timeout_seconds: float) -> bool:
    if timeout_seconds <= 0:
        return stop_event.is_set()
    return stop_event.wait(timeout_seconds)


def _require_executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise RuntimeError(f"required executable {name!r} was not found in PATH")


def _build_signalling_url(port: int) -> str | None:
    addresses = _detect_default_route_addresses()
    if not addresses.ipv6:
        return None
    return f"ws://[{addresses.ipv6}]:{port}"


def _save_runtime_state(
    *,
    path: Path,
    status: str,
    ready: bool,
    signalling_url: str | None,
    stream_name: str,
    last_error: str | None,
) -> None:
    save_media_state(
        {
            "status": status,
            "ready": ready,
            "local": {
                "signallingUrl": signalling_url,
                "streamName": stream_name,
            },
            "codec": {
                "video": DEFAULT_VIDEO_CODEC,
            },
            "viewerConnected": False,
            "lastError": last_error,
            "updatedAt": media_state_timestamp(),
        },
        path,
    )


def _build_gstreamer_command(args: argparse.Namespace, gst_launch_bin: str) -> list[str]:
    source_tokens = shlex.split(args.source_pipeline)
    if not source_tokens:
        raise RuntimeError("--source-pipeline must not be empty")

    sink_tokens = [
        "!",
        "webrtcsink",
        "run-signalling-server=true",
        "run-web-server=false",
        "enable-control-data-channel=false",
        f"signalling-server-host={args.signalling_host}",
        f"signalling-server-port={args.signalling_port}",
        "stun-server=",
        f"meta=meta,name={args.stream_name}",
    ]
    return [gst_launch_bin, "-e", *source_tokens, *sink_tokens]


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    args = _parse_args()
    _configure_logging(args.debug)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    try:
        gst_launch_bin = _require_executable(args.gst_launch_bin)
        command = _build_gstreamer_command(args, gst_launch_bin)
    except RuntimeError as err:
        print(f"board-media start failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    LOGGER.info(
        "Board media service started pid=%s stream_name=%s signalling_host=%s signalling_port=%s",
        os.getpid(),
        args.stream_name,
        args.signalling_host,
        args.signalling_port,
    )
    LOGGER.info("Board media source pipeline: %s", args.source_pipeline)
    LOGGER.info("Board media gst-launch command: %s", shlex.join(command))

    while not stop_event.is_set():
        signalling_url = _build_signalling_url(args.signalling_port)
        _save_runtime_state(
            path=args.state_file,
            status=MEDIA_STATUS_STARTING,
            ready=False,
            signalling_url=signalling_url,
            stream_name=args.stream_name,
            last_error=None,
        )

        process = subprocess.Popen(command)
        LOGGER.info("Started GStreamer media pipeline pid=%s", process.pid)

        if _wait_for_stop(stop_event, args.startup_grace_seconds):
            _terminate_process(process)
            break

        exit_code = process.poll()
        if exit_code is not None:
            error_text = f"media pipeline exited during startup with code {exit_code}"
            LOGGER.error(error_text)
            _save_runtime_state(
                path=args.state_file,
                status=MEDIA_STATUS_ERROR,
                ready=False,
                signalling_url=_build_signalling_url(args.signalling_port),
                stream_name=args.stream_name,
                last_error=error_text,
            )
            if _wait_for_stop(stop_event, args.restart_delay):
                break
            continue

        while not stop_event.is_set():
            exit_code = process.poll()
            if exit_code is not None:
                break

            _save_runtime_state(
                path=args.state_file,
                status=MEDIA_STATUS_READY,
                ready=True,
                signalling_url=_build_signalling_url(args.signalling_port),
                stream_name=args.stream_name,
                last_error=None,
            )
            if _wait_for_stop(stop_event, args.state_write_interval):
                break

        if stop_event.is_set():
            _terminate_process(process)
            _save_runtime_state(
                path=args.state_file,
                status=MEDIA_STATUS_ERROR,
                ready=False,
                signalling_url=_build_signalling_url(args.signalling_port),
                stream_name=args.stream_name,
                last_error="media service stopped",
            )
            break

        exit_code = process.wait()
        error_text = f"media pipeline exited with code {exit_code}"
        LOGGER.warning(error_text)
        _save_runtime_state(
            path=args.state_file,
            status=MEDIA_STATUS_ERROR,
            ready=False,
            signalling_url=_build_signalling_url(args.signalling_port),
            stream_name=args.stream_name,
            last_error=error_text,
        )
        if _wait_for_stop(stop_event, args.restart_delay):
            break
