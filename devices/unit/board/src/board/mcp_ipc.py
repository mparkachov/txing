from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path
from typing import Any

from .mcp_service import BoardMcpServer

LOGGER = logging.getLogger("board.mcp_ipc")


class BoardMcpIpcServer:
    def __init__(
        self,
        *,
        socket_path: Path,
        mcp_server: BoardMcpServer,
    ) -> None:
        self._socket_path = socket_path
        self._mcp_server = mcp_server
        self._stop_event = threading.Event()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._connection_threads: set[threading.Thread] = set()
        self._connection_threads_lock = threading.Lock()

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self._socket_path))
        listener.listen()
        listener.settimeout(0.2)
        self._listener = listener
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="board-mcp-ipc",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("Started board MCP IPC socket path=%s", self._socket_path)

    def stop(self) -> None:
        self._stop_event.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2.0)
        with self._connection_threads_lock:
            connection_threads = list(self._connection_threads)
        for connection_thread in connection_threads:
            connection_thread.join(timeout=2.0)
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    return
                LOGGER.exception("Board MCP IPC accept failed")
                continue
            thread = threading.Thread(
                target=self._handle_connection,
                args=(connection,),
                name="board-mcp-ipc-connection",
                daemon=True,
            )
            with self._connection_threads_lock:
                self._connection_threads.add(thread)
            thread.start()

    def _handle_connection(self, connection: socket.socket) -> None:
        current_thread = threading.current_thread()
        sessions_seen: set[str] = set()
        write_lock = threading.Lock()

        def send_response(session_id: str, payload: bytes) -> None:
            response = {
                "type": "response",
                "sessionId": session_id,
                "payload": payload.decode("utf-8"),
            }
            encoded = (json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n").encode(
                "utf-8"
            )
            with write_lock:
                connection.sendall(encoded)

        try:
            with connection:
                reader = connection.makefile("r", encoding="utf-8", newline="\n")
                for line in reader:
                    if self._stop_event.is_set():
                        break
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Ignored invalid MCP IPC JSON frame")
                        continue
                    session_id = _string_field(message, "sessionId")
                    if not session_id:
                        LOGGER.warning("Ignored MCP IPC frame without sessionId")
                        continue
                    sessions_seen.add(session_id)
                    message_type = _string_field(message, "type")
                    if message_type == "close":
                        self._mcp_server.close_session(
                            session_id=session_id,
                            reason=_string_field(message, "reason") or "MCP WebRTC data channel closed",
                        )
                        sessions_seen.discard(session_id)
                        continue
                    if message_type != "request":
                        LOGGER.warning("Ignored unsupported MCP IPC frame type=%s", message_type)
                        continue
                    payload = _string_field(message, "payload")
                    if payload is None:
                        LOGGER.warning("Ignored MCP IPC request without payload")
                        continue
                    self._mcp_server.handle_session_payload(
                        session_id=session_id,
                        payload_bytes=payload.encode("utf-8"),
                        response_sender=lambda response, sid=session_id: send_response(sid, response),
                    )
        except OSError as err:
            if not self._stop_event.is_set():
                LOGGER.warning("Board MCP IPC connection failed: %s", err)
        finally:
            for session_id in sessions_seen:
                self._mcp_server.close_session(
                    session_id=session_id,
                    reason="MCP WebRTC IPC connection closed",
                )
            with self._connection_threads_lock:
                self._connection_threads.discard(current_thread)


def _string_field(message: Any, field_name: str) -> str | None:
    if not isinstance(message, dict):
        return None
    value = message.get(field_name)
    if not isinstance(value, str):
        return None
    return value
