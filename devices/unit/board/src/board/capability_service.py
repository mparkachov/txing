from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

CAPABILITY_SCHEMA_VERSION = "2.0"
BOARD_CAPABILITY_ADAPTER_ID = "dev.txing.board.Capability"
BOARD_CAPABILITY_NAMES = ("board", "mcp", "video")
DEFAULT_CAPABILITY_STATE_TTL_SECONDS = 150.0
LOGGER = logging.getLogger("board.capability_service")


def build_capability_state_topic(device_id: str) -> str:
    return f"txings/{device_id}/capability/v2/state"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


class BoardCapabilityService:
    def __init__(
        self,
        *,
        device_id: str,
        declared_capabilities: tuple[str, ...],
        adapter_id: str = BOARD_CAPABILITY_ADAPTER_ID,
        ttl_seconds: float = DEFAULT_CAPABILITY_STATE_TTL_SECONDS,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._device_id = device_id
        self._adapter_id = adapter_id
        declared = set(declared_capabilities)
        self._capability_names = tuple(
            capability
            for capability in BOARD_CAPABILITY_NAMES
            if capability in declared
        )
        self._ttl_seconds = ttl_seconds
        self._topic = build_capability_state_topic(device_id)
        self._lock = threading.Lock()
        self._client: Any = None
        self._publish_timeout_seconds: float = 5.0
        self._seq = 0
        self._last_capabilities: dict[str, bool] | None = None

    @property
    def topic(self) -> str:
        return self._topic

    def on_connected(self, *, client: Any, publish_timeout_seconds: float) -> None:
        with self._lock:
            self._client = client
            self._publish_timeout_seconds = publish_timeout_seconds
            payload = (
                self._build_payload_locked(self._last_capabilities)
                if self._last_capabilities is not None
                else None
            )
        if payload is not None:
            self._publish(client, payload, publish_timeout_seconds)

    def on_disconnected(self, *, reason: str) -> None:
        del reason
        with self._lock:
            self._client = None

    def publish_state(
        self,
        *,
        board_available: bool,
        mcp_available: bool,
        video_available: bool,
    ) -> None:
        if not self._capability_names:
            return
        requested = {
            "board": board_available,
            "mcp": mcp_available,
            "video": video_available,
        }
        capabilities = {
            capability: bool(requested[capability])
            for capability in self._capability_names
        }
        with self._lock:
            self._last_capabilities = capabilities
            payload = self._build_payload_locked(capabilities)
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
        if client is not None:
            self._publish(client, payload, timeout_seconds)

    def close(self) -> None:
        if not self._capability_names:
            return
        capabilities = {capability: False for capability in self._capability_names}
        with self._lock:
            self._last_capabilities = capabilities
            payload = self._build_payload_locked(capabilities)
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
            self._client = None
        if client is not None:
            try:
                self._publish(client, payload, timeout_seconds)
            except Exception as err:
                LOGGER.warning("Failed to publish retained capability unavailable state: %s", err)

    def _build_payload_locked(self, capabilities: dict[str, bool] | None) -> bytes:
        if capabilities is None:
            raise ValueError("capabilities must not be None")
        self._seq += 1
        observed_at_ms = _now_ms()
        expires_at_ms = observed_at_ms + int(self._ttl_seconds * 1000)
        expired_capabilities = {
            capability: False
            for capability in capabilities
        }
        return _encode_json(
            {
                "schemaVersion": CAPABILITY_SCHEMA_VERSION,
                "adapterId": self._adapter_id,
                "thingName": self._device_id,
                "capabilities": capabilities,
                "metrics": {},
                "observedAtMs": observed_at_ms,
                "seq": self._seq,
                "expiresAtMs": expires_at_ms,
                "expiredCapabilities": expired_capabilities,
            }
        )

    def _publish(
        self,
        client: Any,
        payload: bytes,
        timeout_seconds: float,
    ) -> None:
        client.publish(
            self._topic,
            payload,
            retain=True,
            timeout_seconds=timeout_seconds,
        )
