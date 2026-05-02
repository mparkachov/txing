from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from aws.video_topics import (
    VIDEO_STATUS_UNAVAILABLE,
    build_video_descriptor_payload,
    build_video_status_payload,
    build_video_topics,
)

from .video_state import normalize_video_state

LOGGER = logging.getLogger("board.video_service")

DEFAULT_VIDEO_SERVER_VERSION = "0.6.0"


def _encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _server_version_from_env() -> str:
    return os.getenv("TXING_VERSION", "").strip() or DEFAULT_VIDEO_SERVER_VERSION


class BoardVideoService:
    def __init__(
        self,
        *,
        device_id: str,
        channel_name: str,
        region: str,
        server_version: str | None = None,
    ) -> None:
        self._device_id = device_id
        self._channel_name = channel_name
        self._region = region
        effective_server_version = server_version or _server_version_from_env()
        self._topics = build_video_topics(device_id)
        self._descriptor_payload = build_video_descriptor_payload(
            device_id=device_id,
            channel_name=channel_name,
            region=region,
            server_version=effective_server_version,
        )
        self._lock = threading.Lock()
        self._client: Any = None
        self._publish_timeout_seconds: float = 5.0
        self._last_status_payload: bytes | None = None

    @property
    def descriptor_topic(self) -> str:
        return self._topics.descriptor

    @property
    def status_topic(self) -> str:
        return self._topics.status

    def build_descriptor_payload(self) -> dict[str, Any]:
        return dict(self._descriptor_payload)

    def build_status_payload(self, video_state: dict[str, Any] | None) -> dict[str, Any]:
        normalized = normalize_video_state(
            video_state,
            channel_name=self._channel_name,
        )
        return build_video_status_payload(
            available=True,
            ready=bool(normalized["ready"]),
            status=normalized["status"],
            viewer_connected=bool(normalized["viewerConnected"]),
            last_error=(
                normalized["lastError"]
                if isinstance(normalized["lastError"], str)
                else None
            ),
            updated_at_ms=_now_ms(),
        )

    def build_unavailable_status_payload(self) -> bytes:
        return _encode_json(
            build_video_status_payload(
                available=False,
                ready=False,
                status=VIDEO_STATUS_UNAVAILABLE,
                viewer_connected=False,
                last_error=None,
                updated_at_ms=_now_ms(),
            )
        )

    def on_connected(self, *, client: Any, publish_timeout_seconds: float) -> None:
        with self._lock:
            self._client = client
            self._publish_timeout_seconds = publish_timeout_seconds
            self._publish_descriptor_locked()
            self._publish_last_status_locked()

    def on_disconnected(self, *, reason: str) -> None:
        with self._lock:
            self._client = None
        LOGGER.info("Board video service disconnected: %s", reason)

    def close(self) -> None:
        with self._lock:
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
            payload = self.build_unavailable_status_payload()
            self._client = None
        if client is None:
            return
        try:
            client.publish(
                self._topics.status,
                payload,
                retain=True,
                timeout_seconds=timeout_seconds,
            )
        except Exception as err:
            LOGGER.warning("Failed to publish retained video unavailable status: %s", err)

    def publish_status(self, video_state: dict[str, Any] | None) -> None:
        payload = self._build_status_payload(video_state)
        with self._lock:
            self._last_status_payload = payload
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
        if client is None:
            return
        client.publish(
            self._topics.status,
            payload,
            retain=True,
            timeout_seconds=timeout_seconds,
        )

    def _publish_descriptor_locked(self) -> None:
        if self._client is None:
            return
        self._client.publish(
            self._topics.descriptor,
            _encode_json(self._descriptor_payload),
            retain=True,
            timeout_seconds=self._publish_timeout_seconds,
        )

    def _publish_last_status_locked(self) -> None:
        if self._client is None or self._last_status_payload is None:
            return
        self._client.publish(
            self._topics.status,
            self._last_status_payload,
            retain=True,
            timeout_seconds=self._publish_timeout_seconds,
        )

    def _build_status_payload(self, video_state: dict[str, Any] | None) -> bytes:
        return _encode_json(self.build_status_payload(video_state))
