from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from aws.mcp_topics import (
    MCP_DEFAULT_LEASE_TTL_MS,
    MCP_PROTOCOL_VERSION,
    build_mcp_descriptor_payload,
    build_mcp_session_c2s_topic,
    build_mcp_session_s2c_topic,
    build_mcp_status_payload,
    build_mcp_topics,
    parse_mcp_session_c2s_topic,
)

from .cmd_vel import CmdVelController
from .video_state import (
    VIDEO_STATUS_ERROR,
    VIDEO_STATUS_STARTING,
    normalize_video_state,
)

LOGGER = logging.getLogger("board.mcp_service")

MCP_SERVER_VERSION = "0.2.0"
_JSONRPC_VERSION = "2.0"


def _encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True, frozen=True)
class _LeaseState:
    owner_session_id: str
    token: str
    expires_at_monotonic: float
    expires_at_ms: int


class BoardMcpServer:
    def __init__(
        self,
        *,
        device_id: str,
        cmd_vel_controller: CmdVelController,
        video_state_provider: Callable[[], dict[str, Any]] | None = None,
        lease_ttl_ms: int = MCP_DEFAULT_LEASE_TTL_MS,
        server_version: str = MCP_SERVER_VERSION,
        mcp_protocol_version: str = MCP_PROTOCOL_VERSION,
    ) -> None:
        if lease_ttl_ms <= 0:
            raise ValueError("lease_ttl_ms must be positive")
        self._device_id = device_id
        self._cmd_vel_controller = cmd_vel_controller
        self._video_state_provider = video_state_provider
        self._lease_ttl_ms = lease_ttl_ms
        self._server_version = server_version
        self._mcp_protocol_version = mcp_protocol_version
        self._topics = build_mcp_topics(device_id)
        self._descriptor_payload = build_mcp_descriptor_payload(
            device_id=device_id,
            server_version=server_version,
            lease_required=True,
            lease_ttl_ms=lease_ttl_ms,
            mcp_protocol_version=mcp_protocol_version,
        )
        self._lock = threading.Lock()
        self._lease: _LeaseState | None = None
        self._available = False
        self._initialized_sessions: set[str] = set()
        self._client: Any = None
        self._publish_timeout_seconds: float = 5.0

    @property
    def descriptor_topic(self) -> str:
        return self._topics.descriptor

    @property
    def status_topic(self) -> str:
        return self._topics.status

    @property
    def session_c2s_subscription(self) -> str:
        return self._topics.session_c2s_subscription

    def build_unavailable_status_payload(self) -> bytes:
        with self._lock:
            return self._build_status_payload_locked(available=False)

    def on_connected(self, *, client: Any, publish_timeout_seconds: float) -> None:
        with self._lock:
            self._client = client
            self._publish_timeout_seconds = publish_timeout_seconds
            self._available = True
            self._publish_descriptor_locked()
            self._publish_status_locked()

    def on_disconnected(self, *, reason: str) -> None:
        with self._lock:
            self._available = False
            self._client = None
            self._clear_lease_locked(
                reason=reason,
                publish_status=False,
                clear_initialized_sessions=True,
            )

    def close(self) -> None:
        with self._lock:
            self._available = False
            self._clear_lease_locked(
                reason="board mcp server closed",
                publish_status=False,
                clear_initialized_sessions=True,
            )
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
            payload = self._build_status_payload_locked(available=False)
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
            LOGGER.warning("Failed to publish retained MCP unavailable status: %s", err)

    def poll(self) -> None:
        with self._lock:
            self._expire_lease_locked(now_monotonic=time.monotonic())

    def handles_topic(self, topic: str) -> bool:
        return (
            parse_mcp_session_c2s_topic(
                topic,
                device_id=self._device_id,
            )
            is not None
        )

    def handle_session_message(self, topic: str, payload_bytes: bytes) -> bool:
        session_id = parse_mcp_session_c2s_topic(
            topic,
            device_id=self._device_id,
        )
        if session_id is None:
            return False

        try:
            message = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(
                session_id=session_id,
                request_id=None,
                code=-32700,
                message="Invalid JSON payload",
            )
            return True

        if not isinstance(message, dict):
            self._send_error(
                session_id=session_id,
                request_id=None,
                code=-32600,
                message="Invalid JSON-RPC envelope",
            )
            return True

        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            self._send_error(
                session_id=session_id,
                request_id=request_id,
                code=-32600,
                message="Missing JSON-RPC method",
            )
            return True

        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            self._send_error(
                session_id=session_id,
                request_id=request_id,
                code=-32602,
                message="JSON-RPC params must be an object",
            )
            return True

        if request_id is None:
            self._handle_notification(session_id=session_id, method=method)
            return True

        try:
            result = self._handle_request(
                session_id=session_id,
                method=method,
                params=params or {},
            )
        except _JsonRpcError as err:
            self._send_error(
                session_id=session_id,
                request_id=request_id,
                code=err.code,
                message=err.message,
            )
            return True
        except Exception:
            LOGGER.exception("Unhandled MCP request failure method=%s session=%s", method, session_id)
            self._send_error(
                session_id=session_id,
                request_id=request_id,
                code=-32603,
                message="Internal MCP server error",
            )
            return True

        self._send_result(
            session_id=session_id,
            request_id=request_id,
            result=result,
        )
        return True

    def _handle_notification(self, *, session_id: str, method: str) -> None:
        if method == "notifications/initialized":
            with self._lock:
                self._initialized_sessions.add(session_id)
            return
        LOGGER.debug("Ignoring unsupported MCP notification method=%s session=%s", method, session_id)

    def _handle_request(
        self,
        *,
        session_id: str,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            self._expire_lease_locked(now_monotonic=time.monotonic())
            if method == "initialize":
                return {
                    "protocolVersion": self._mcp_protocol_version,
                    "serverInfo": {
                        "name": "mcp",
                        "version": self._server_version,
                    },
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        },
                    },
                }

            if method == "tools/list":
                self._require_initialized_locked(session_id=session_id)
                return {"tools": _tool_definitions()}

            if method != "tools/call":
                raise _JsonRpcError(-32601, f"Unsupported MCP method: {method}")

            self._require_initialized_locked(session_id=session_id)

        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise _JsonRpcError(-32602, "tools/call requires a non-empty string name")
        raw_arguments = params.get("arguments", {})
        if raw_arguments is None:
            arguments: dict[str, Any] = {}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            raise _JsonRpcError(-32602, "tools/call arguments must be an object")

        structured = self._dispatch_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        return {
            "content": [
                {
                    "type": "json",
                    "json": structured,
                }
            ],
            "structuredContent": structured,
            "isError": False,
        }

    def _dispatch_tool_call(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "control.acquire_lease":
            return self._tool_acquire_lease(session_id=session_id)
        if tool_name == "control.renew_lease":
            return self._tool_renew_lease(
                session_id=session_id,
                lease_token=_require_lease_token(arguments),
            )
        if tool_name == "control.release_lease":
            return self._tool_release_lease(
                session_id=session_id,
                lease_token=_require_lease_token(arguments),
            )
        if tool_name == "cmd_vel.publish":
            twist = arguments.get("twist")
            if not isinstance(twist, dict):
                raise _JsonRpcError(-32602, "cmd_vel.publish requires object argument twist")
            return self._tool_cmd_vel_publish(
                session_id=session_id,
                lease_token=_require_lease_token(arguments),
                twist=twist,
            )
        if tool_name == "cmd_vel.stop":
            return self._tool_cmd_vel_stop(
                session_id=session_id,
                lease_token=_require_lease_token(arguments),
            )
        if tool_name == "robot.get_state":
            return self._tool_robot_get_state(session_id=session_id)
        raise _JsonRpcError(-32602, f"Unknown MCP tool: {tool_name}")

    def _tool_acquire_lease(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            now_monotonic = time.monotonic()
            self._expire_lease_locked(now_monotonic=now_monotonic)
            if self._lease is not None and self._lease.owner_session_id != session_id:
                raise _JsonRpcError(
                    -32010,
                    f"lease is already owned by session {self._lease.owner_session_id}",
                )
            lease = self._create_lease_locked(
                session_id=session_id,
                now_monotonic=now_monotonic,
            )
            self._publish_status_locked()
            return _lease_result_payload(lease=lease, lease_ttl_ms=self._lease_ttl_ms)

    def _tool_renew_lease(
        self,
        *,
        session_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_active_lease_locked(
                session_id=session_id,
                lease_token=lease_token,
            )
            lease = self._create_lease_locked(
                session_id=session_id,
                now_monotonic=time.monotonic(),
            )
            self._publish_status_locked()
            return _lease_result_payload(lease=lease, lease_ttl_ms=self._lease_ttl_ms)

    def _tool_release_lease(
        self,
        *,
        session_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_active_lease_locked(
                session_id=session_id,
                lease_token=lease_token,
            )
            self._clear_lease_locked(
                reason=f"MCP lease released by session {session_id}",
                publish_status=True,
            )
        return {"released": True}

    def _tool_cmd_vel_publish(
        self,
        *,
        session_id: str,
        lease_token: str,
        twist: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_active_lease_locked(
                session_id=session_id,
                lease_token=lease_token,
            )

        handled = self._cmd_vel_controller.handle_message(twist)
        if not handled:
            raise _JsonRpcError(-32602, "cmd_vel.publish twist payload is malformed")
        motion = self._build_motion_payload()
        return {
            "applied": True,
            "leaseExpiresAtMs": lease.expires_at_ms,
            "motion": motion,
        }

    def _tool_cmd_vel_stop(
        self,
        *,
        session_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_active_lease_locked(
                session_id=session_id,
                lease_token=lease_token,
            )
        self._cmd_vel_controller.stop(
            reason=f"cmd_vel.stop from MCP session {session_id}",
            force=True,
        )
        motion = self._build_motion_payload()
        return {
            "stopped": True,
            "leaseExpiresAtMs": lease.expires_at_ms,
            "motion": motion,
        }

    def _tool_robot_get_state(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._expire_lease_locked(now_monotonic=time.monotonic())
            lease = self._lease
            control = {
                "leaseRequired": True,
                "leaseTtlMs": self._lease_ttl_ms,
                "leaseHeldByCaller": lease is not None and lease.owner_session_id == session_id,
                "leaseOwnerSessionId": lease.owner_session_id if lease is not None else None,
                "leaseExpiresAtMs": lease.expires_at_ms if lease is not None else None,
            }
        return {
            "control": control,
            "motion": self._build_motion_payload(),
            "video": self._build_video_payload(),
        }

    def _send_result(
        self,
        *,
        session_id: str,
        request_id: Any,
        result: dict[str, Any],
    ) -> None:
        payload = _encode_json(
            {
                "jsonrpc": _JSONRPC_VERSION,
                "id": request_id,
                "result": result,
            }
        )
        self._publish_session_payload(session_id=session_id, payload=payload)

    def _send_error(
        self,
        *,
        session_id: str,
        request_id: Any,
        code: int,
        message: str,
    ) -> None:
        payload = _encode_json(
            {
                "jsonrpc": _JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        )
        self._publish_session_payload(session_id=session_id, payload=payload)

    def _publish_session_payload(self, *, session_id: str, payload: bytes) -> None:
        with self._lock:
            client = self._client
            timeout_seconds = self._publish_timeout_seconds
        if client is None:
            return
        try:
            client.publish(
                build_mcp_session_s2c_topic(self._device_id, session_id),
                payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as err:
            LOGGER.warning(
                "Failed to publish MCP response topic=%s session=%s: %s (%r)",
                build_mcp_session_s2c_topic(self._device_id, session_id),
                session_id,
                err,
                err,
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

    def _publish_status_locked(self) -> None:
        if self._client is None:
            return
        self._client.publish(
            self._topics.status,
            self._build_status_payload_locked(available=self._available),
            retain=True,
            timeout_seconds=self._publish_timeout_seconds,
        )

    def _build_status_payload_locked(self, *, available: bool) -> bytes:
        lease_owner: str | None = None
        lease_expires: int | None = None
        if self._lease is not None:
            lease_owner = self._lease.owner_session_id
            lease_expires = self._lease.expires_at_ms
        return _encode_json(
            build_mcp_status_payload(
                available=available,
                lease_owner_session_id=lease_owner,
                lease_expires_at_ms=lease_expires,
                updated_at_ms=_now_ms(),
            )
        )

    def _expire_lease_locked(self, *, now_monotonic: float) -> None:
        lease = self._lease
        if lease is None:
            return
        if now_monotonic < lease.expires_at_monotonic:
            return
        self._clear_lease_locked(reason="MCP lease expired", publish_status=True)

    def _clear_lease_locked(
        self,
        *,
        reason: str,
        publish_status: bool,
        clear_initialized_sessions: bool = False,
    ) -> None:
        self._lease = None
        if clear_initialized_sessions:
            self._initialized_sessions.clear()
        self._cmd_vel_controller.stop(reason=reason, force=True)
        if publish_status:
            self._publish_status_locked()

    def _create_lease_locked(self, *, session_id: str, now_monotonic: float) -> _LeaseState:
        expires_at_monotonic = now_monotonic + (self._lease_ttl_ms / 1000.0)
        lease = _LeaseState(
            owner_session_id=session_id,
            token=secrets.token_hex(16),
            expires_at_monotonic=expires_at_monotonic,
            expires_at_ms=_now_ms() + self._lease_ttl_ms,
        )
        self._lease = lease
        return lease

    def _require_initialized_locked(self, *, session_id: str) -> None:
        if session_id in self._initialized_sessions:
            return
        raise _JsonRpcError(-32000, "MCP session is not initialized")

    def _require_active_lease_locked(
        self,
        *,
        session_id: str,
        lease_token: str,
    ) -> _LeaseState:
        self._expire_lease_locked(now_monotonic=time.monotonic())
        lease = self._lease
        if lease is None:
            raise _JsonRpcError(-32011, "No active control lease")
        if lease.owner_session_id != session_id:
            raise _JsonRpcError(
                -32012,
                f"Lease is owned by another session ({lease.owner_session_id})",
            )
        if lease.token != lease_token:
            raise _JsonRpcError(-32013, "Invalid lease token")
        return lease

    def _build_motion_payload(self) -> dict[str, int]:
        state = self._cmd_vel_controller.get_drive_state()
        return {
            "leftSpeed": state.left_speed,
            "rightSpeed": state.right_speed,
            "sequence": state.sequence,
        }

    def _build_video_payload(self) -> dict[str, Any]:
        payload = self._read_video_state_payload()
        return {
            "available": payload["available"],
            "ready": payload["ready"],
            "status": payload["status"],
            "viewerConnected": payload["viewerConnected"],
            "lastError": payload["lastError"],
        }

    def _read_video_state_payload(self) -> dict[str, Any]:
        if self._video_state_provider is None:
            return {
                "available": False,
                "ready": False,
                "status": VIDEO_STATUS_STARTING,
                "viewerConnected": False,
                "lastError": None,
            }
        try:
            payload = self._video_state_provider()
        except Exception as err:
            LOGGER.warning("Failed to read board video state for MCP: %s", err)
            return {
                "available": False,
                "ready": False,
                "status": VIDEO_STATUS_ERROR,
                "viewerConnected": False,
                "lastError": str(err),
            }
        normalized = normalize_video_state(payload)
        return {
            "available": True,
            "ready": bool(normalized["ready"]),
            "status": normalized["status"],
            "viewerConnected": bool(normalized["viewerConnected"]),
            "lastError": normalized["lastError"],
        }


@dataclass(slots=True, frozen=True)
class _JsonRpcError(Exception):
    code: int
    message: str


def _require_lease_token(arguments: dict[str, Any]) -> str:
    lease_token = arguments.get("leaseToken")
    if not isinstance(lease_token, str) or not lease_token:
        raise _JsonRpcError(-32602, "Missing non-empty string leaseToken")
    return lease_token


def _lease_result_payload(*, lease: _LeaseState, lease_ttl_ms: int) -> dict[str, Any]:
    return {
        "leaseToken": lease.token,
        "leaseTtlMs": lease_ttl_ms,
        "expiresAtMs": lease.expires_at_ms,
        "ownerSessionId": lease.owner_session_id,
    }


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "control.acquire_lease",
            "description": "Acquire exclusive teleop control lease for this MCP session.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "control.renew_lease",
            "description": "Renew the current teleop control lease before expiry.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "leaseToken": {"type": "string"},
                },
                "required": ["leaseToken"],
                "additionalProperties": False,
            },
        },
        {
            "name": "control.release_lease",
            "description": "Release the teleop lease and stop motion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "leaseToken": {"type": "string"},
                },
                "required": ["leaseToken"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cmd_vel.publish",
            "description": "Publish a Twist command while holding a valid control lease.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "leaseToken": {"type": "string"},
                    "twist": {"type": "object"},
                },
                "required": ["leaseToken", "twist"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cmd_vel.stop",
            "description": "Stop motion while keeping the lease active.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "leaseToken": {"type": "string"},
                },
                "required": ["leaseToken"],
                "additionalProperties": False,
            },
        },
        {
            "name": "robot.get_state",
            "description": "Return the current board control, motion, and video runtime snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]
