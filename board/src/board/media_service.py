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
    DEFAULT_MEDIAMTX_RTSP_PORT,
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_STREAM_PATH,
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
DEFAULT_RTSP_PUBLISH_HOST = "127.0.0.1"
DEFAULT_SOURCE_PIPELINE = (
    "libcamerasrc "
    "! capsfilter caps=video/x-raw,width=1920,height=1080,framerate=30/1,format=NV12,interlace-mode=progressive "
    '! v4l2h264enc extra-controls="controls,repeat_sequence_header=1" '
    "! h264parse config-interval=-1"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Txing board-local GStreamer to MediaMTX publisher",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_MEDIA_STATE_FILE,
        help=f"Path to runtime media state file (default: {DEFAULT_MEDIA_STATE_FILE})",
    )
    parser.add_argument(
        "--stream-path",
        default=DEFAULT_STREAM_PATH,
        help=f"Published MediaMTX stream path (default: {DEFAULT_STREAM_PATH})",
    )
    parser.add_argument(
        "--viewer-port",
        type=int,
        default=DEFAULT_MEDIAMTX_VIEWER_PORT,
        help=f"Published MediaMTX WebRTC viewer port (default: {DEFAULT_MEDIAMTX_VIEWER_PORT})",
    )
    parser.add_argument(
        "--rtsp-publish-host",
        default=DEFAULT_RTSP_PUBLISH_HOST,
        help=f"MediaMTX RTSP publish host (default: {DEFAULT_RTSP_PUBLISH_HOST})",
    )
    parser.add_argument(
        "--rtsp-publish-port",
        type=int,
        default=DEFAULT_MEDIAMTX_RTSP_PORT,
        help=f"MediaMTX RTSP publish port (default: {DEFAULT_MEDIAMTX_RTSP_PORT})",
    )
    parser.add_argument(
        "--gst-launch-bin",
        default=DEFAULT_GST_LAUNCH_BIN,
        help=f"gst-launch executable to run (default: {DEFAULT_GST_LAUNCH_BIN})",
    )
    parser.add_argument(
        "--source-pipeline",
        default=DEFAULT_SOURCE_PIPELINE,
        help="GStreamer source fragment ending in H.264 before RTSP publish",
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


def _build_viewer_url(port: int, stream_path: str) -> str | None:
    addresses = _detect_default_route_addresses()
    if not addresses.ipv6:
        return None
    normalized_path = stream_path.strip().strip("/")
    if not normalized_path:
        return None
    return f"http://[{addresses.ipv6}]:{port}/{normalized_path}"


def _build_publish_url(*, host: str, port: int, stream_path: str) -> str:
    normalized_path = stream_path.strip().strip("/")
    if not normalized_path:
        raise RuntimeError("--stream-path must not be empty")
    return f"rtsp://{host}:{port}/{normalized_path}"


def _save_runtime_state(
    *,
    path: Path,
    status: str,
    ready: bool,
    viewer_url: str | None,
    stream_path: str,
    last_error: str | None,
) -> None:
    save_media_state(
        {
            "status": status,
            "ready": ready,
            "local": {
                "viewerUrl": viewer_url,
                "streamPath": stream_path,
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

    publish_url = _build_publish_url(
        host=args.rtsp_publish_host,
        port=args.rtsp_publish_port,
        stream_path=args.stream_path,
    )

    sink_tokens = [
        "!",
        "rtph264pay",
        "pt=96",
        "config-interval=1",
        "!",
        "rtspclientsink",
        f"location={publish_url}",
        "protocols=tcp",
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
        "Board media service started pid=%s stream_path=%s rtsp_publish_host=%s rtsp_publish_port=%s viewer_port=%s",
        os.getpid(),
        args.stream_path,
        args.rtsp_publish_host,
        args.rtsp_publish_port,
        args.viewer_port,
    )
    LOGGER.info("Board media source pipeline: %s", args.source_pipeline)
    LOGGER.info("Board media gst-launch command: %s", shlex.join(command))

    while not stop_event.is_set():
        _save_runtime_state(
            path=args.state_file,
            status=MEDIA_STATUS_STARTING,
            ready=False,
            viewer_url=_build_viewer_url(args.viewer_port, args.stream_path),
            stream_path=args.stream_path,
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
                viewer_url=_build_viewer_url(args.viewer_port, args.stream_path),
                stream_path=args.stream_path,
                last_error=error_text,
            )
            if _wait_for_stop(stop_event, args.restart_delay):
                break
            continue

        while not stop_event.is_set():
            exit_code = process.poll()
            if exit_code is not None:
                break

            viewer_url = _build_viewer_url(args.viewer_port, args.stream_path)
            last_error = None
            status = MEDIA_STATUS_READY
            ready = True
            if viewer_url is None:
                status = MEDIA_STATUS_ERROR
                ready = False
                last_error = "board has no global IPv6 address for MediaMTX viewer URL"

            _save_runtime_state(
                path=args.state_file,
                status=status,
                ready=ready,
                viewer_url=viewer_url,
                stream_path=args.stream_path,
                last_error=last_error,
            )
            if _wait_for_stop(stop_event, args.state_write_interval):
                break

        if stop_event.is_set():
            _terminate_process(process)
            _save_runtime_state(
                path=args.state_file,
                status=MEDIA_STATUS_ERROR,
                ready=False,
                viewer_url=_build_viewer_url(args.viewer_port, args.stream_path),
                stream_path=args.stream_path,
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
            viewer_url=_build_viewer_url(args.viewer_port, args.stream_path),
            stream_path=args.stream_path,
            last_error=error_text,
        )
        if _wait_for_stop(stop_event, args.restart_delay):
            break
