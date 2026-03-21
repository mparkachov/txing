from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .media_state import (
    DEFAULT_MEDIA_STATE_FILE,
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

DEFAULT_STATE_WRITE_INTERVAL = 5.0
DEFAULT_STARTUP_GRACE_SECONDS = 2.0
DEFAULT_PROBE_HOST = "127.0.0.1"
DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Txing board-local MediaMTX runtime state reporter",
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
        "--viewer-host",
        default="",
        help="Optional hostname or address to publish in viewerUrl (default: auto-detect IPv4, then IPv6)",
    )
    parser.add_argument(
        "--probe-host",
        default=DEFAULT_PROBE_HOST,
        help=f"Local host to probe for the MediaMTX viewer page (default: {DEFAULT_PROBE_HOST})",
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
        help=f"Seconds before MediaMTX probe failures are marked as errors (default: {DEFAULT_STARTUP_GRACE_SECONDS})",
    )
    parser.add_argument(
        "--probe-timeout-seconds",
        type=float,
        default=DEFAULT_PROBE_TIMEOUT_SECONDS,
        help=f"HTTP timeout for probing MediaMTX (default: {DEFAULT_PROBE_TIMEOUT_SECONDS})",
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


def _build_http_url(host: str, port: int, stream_path: str) -> str:
    normalized_path = stream_path.strip().strip("/")
    if not normalized_path:
        raise RuntimeError("--stream-path must not be empty")
    host_value = host.strip()
    if not host_value:
        raise RuntimeError("HTTP host must not be empty")
    if ":" in host_value and not host_value.startswith("["):
        host_value = f"[{host_value}]"
    return f"http://{host_value}:{port}/{normalized_path}/"


def _detect_viewer_host(override: str) -> str | None:
    stripped_override = override.strip()
    if stripped_override:
        return stripped_override

    addresses = _detect_default_route_addresses()
    return addresses.ipv4 or addresses.ipv6


def _probe_viewer_page(*, host: str, port: int, stream_path: str, timeout_seconds: float) -> str | None:
    probe_url = _build_http_url(host, port, stream_path)
    request = Request(probe_url, headers={"User-Agent": "txing-board-media/1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = getattr(response, "status", 200)
            if 200 <= status_code < 400:
                return None
            return f"MediaMTX probe returned HTTP {status_code}"
    except HTTPError as err:
        return f"MediaMTX probe returned HTTP {err.code}"
    except URLError as err:
        return f"MediaMTX probe failed: {err.reason}"
    except OSError as err:
        return f"MediaMTX probe failed: {err}"


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


def main() -> None:
    args = _parse_args()
    _configure_logging(args.debug)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    LOGGER.info(
        "Board media service started pid=%s stream_path=%s viewer_host=%s probe_host=%s viewer_port=%s",
        os.getpid(),
        args.stream_path,
        args.viewer_host or "<auto>",
        args.probe_host,
        args.viewer_port,
    )
    service_started_at = time.monotonic()

    while not stop_event.is_set():
        viewer_host = _detect_viewer_host(args.viewer_host)
        viewer_url = None
        local_error = None
        if viewer_host is None:
            local_error = "board has no default-route IPv4 or IPv6 address for MediaMTX viewer URL"
        else:
            viewer_url = _build_http_url(viewer_host, args.viewer_port, args.stream_path)
            local_error = _probe_viewer_page(
                host=args.probe_host,
                port=args.viewer_port,
                stream_path=args.stream_path,
                timeout_seconds=args.probe_timeout_seconds,
            )

        elapsed = time.monotonic() - service_started_at
        if local_error is None and viewer_url is not None:
            status = MEDIA_STATUS_READY
            ready = True
            last_error = None
        elif elapsed < args.startup_grace_seconds:
            status = MEDIA_STATUS_STARTING
            ready = False
            last_error = None
        else:
            status = MEDIA_STATUS_ERROR
            ready = False
            last_error = local_error

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

    _save_runtime_state(
        path=args.state_file,
        status=MEDIA_STATUS_ERROR,
        ready=False,
        viewer_url=None,
        stream_path=args.stream_path,
        last_error="media service stopped",
    )


if __name__ == "__main__":
    main()
