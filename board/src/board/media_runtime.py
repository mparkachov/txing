from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .media_state import (
    DEFAULT_MEDIAMTX_VIEWER_PORT,
    DEFAULT_STREAM_PATH,
    DEFAULT_VIDEO_CODEC,
    MEDIA_STATUS_ERROR,
    MEDIA_STATUS_READY,
)

DEFAULT_PROBE_HOST = "127.0.0.1"
DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0


def _normalize_stream_path(stream_path: str) -> str:
    normalized_path = stream_path.strip().strip("/")
    if not normalized_path:
        raise RuntimeError("--stream-path must not be empty")
    return normalized_path


def build_http_url(host: str, port: int, stream_path: str) -> str:
    normalized_path = _normalize_stream_path(stream_path)
    host_value = host.strip()
    if not host_value:
        raise RuntimeError("HTTP host must not be empty")
    if ":" in host_value and not host_value.startswith("["):
        host_value = f"[{host_value}]"
    return f"http://{host_value}:{port}/{normalized_path}/"


def detect_viewer_host(override: str, *, ipv4: str | None, ipv6: str | None) -> str | None:
    stripped_override = override.strip()
    if stripped_override:
        return stripped_override
    return ipv4 or ipv6


def probe_viewer_page(
    *,
    host: str,
    port: int,
    stream_path: str,
    timeout_seconds: float,
) -> str | None:
    probe_url = build_http_url(host, port, stream_path)
    request = Request(probe_url, headers={"User-Agent": "txing-board/1"})
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


def build_live_media_state(
    *,
    stream_path: str = DEFAULT_STREAM_PATH,
    viewer_port: int = DEFAULT_MEDIAMTX_VIEWER_PORT,
    viewer_host_override: str = "",
    probe_host: str = DEFAULT_PROBE_HOST,
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    route_ipv4: str | None,
    route_ipv6: str | None,
) -> dict[str, Any]:
    normalized_stream_path = _normalize_stream_path(stream_path)
    viewer_host = detect_viewer_host(
        viewer_host_override,
        ipv4=route_ipv4,
        ipv6=route_ipv6,
    )
    viewer_url = None
    local_error = None

    if viewer_host is None:
        local_error = "board has no default-route IPv4 or IPv6 address for MediaMTX viewer URL"
    else:
        viewer_url = build_http_url(viewer_host, viewer_port, normalized_stream_path)
        local_error = probe_viewer_page(
            host=probe_host,
            port=viewer_port,
            stream_path=normalized_stream_path,
            timeout_seconds=probe_timeout_seconds,
        )

    if local_error is None and viewer_url is not None:
        status = MEDIA_STATUS_READY
        ready = True
        last_error = None
    else:
        status = MEDIA_STATUS_ERROR
        ready = False
        last_error = local_error

    return {
        "status": status,
        "ready": ready,
        "local": {
            "viewerUrl": viewer_url,
            "streamPath": normalized_stream_path,
        },
        "codec": {
            "video": DEFAULT_VIDEO_CODEC,
        },
        "viewerConnected": False,
        "lastError": last_error,
    }
