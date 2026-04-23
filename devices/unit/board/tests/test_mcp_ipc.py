from __future__ import annotations

import json
import socket
import time
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from board.cmd_vel import DriveState
from board.mcp_ipc import BoardMcpIpcServer
from board.mcp_service import BoardMcpServer


@dataclass(slots=True)
class _FakeCmdVelController:
    stop_reasons: list[str]
    drive_state: DriveState

    def handle_message(self, payload: Any) -> bool:
        del payload
        self.drive_state = DriveState(30, 30, self.drive_state.sequence + 1)
        return True

    def stop(self, *, reason: str, force: bool = False) -> None:
        del force
        self.stop_reasons.append(reason)
        self.drive_state = DriveState(0, 0, self.drive_state.sequence + 1)

    def get_drive_state(self) -> DriveState:
        return self.drive_state


def _send_frame(sock: socket.socket, frame: dict[str, Any]) -> None:
    sock.sendall((json.dumps(frame, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))


class BoardMcpIpcServerTests(unittest.TestCase):
    def test_dispatches_request_and_closes_owned_session(self) -> None:
        cmd_vel = _FakeCmdVelController(stop_reasons=[], drive_state=DriveState(0, 0, 0))
        mcp_server = BoardMcpServer(
            device_id="unit-local",
            cmd_vel_controller=cmd_vel,
            lease_ttl_ms=5000,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "mcp.sock"
            ipc_server = BoardMcpIpcServer(socket_path=socket_path, mcp_server=mcp_server)
            ipc_server.start()
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(2.0)
                    client.connect(str(socket_path))
                    reader = client.makefile("r", encoding="utf-8", newline="\n")

                    _send_frame(
                        client,
                        {
                            "type": "request",
                            "sessionId": "webrtc-session-a",
                            "payload": json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "initialize",
                                    "params": {},
                                }
                            ),
                        },
                    )
                    initialize_response = json.loads(reader.readline())
                    self.assertEqual(initialize_response["type"], "response")
                    self.assertEqual(initialize_response["sessionId"], "webrtc-session-a")
                    self.assertEqual(
                        json.loads(initialize_response["payload"])["result"]["serverInfo"]["name"],
                        "mcp",
                    )

                    _send_frame(
                        client,
                        {
                            "type": "request",
                            "sessionId": "webrtc-session-a",
                            "payload": json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "method": "notifications/initialized",
                                    "params": {},
                                }
                            ),
                        },
                    )
                    _send_frame(
                        client,
                        {
                            "type": "request",
                            "sessionId": "webrtc-session-a",
                            "payload": json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 2,
                                    "method": "tools/call",
                                    "params": {
                                        "name": "control.acquire_lease",
                                        "arguments": {},
                                    },
                                }
                            ),
                        },
                    )
                    acquire_response = json.loads(reader.readline())
                    self.assertIn(
                        "leaseToken",
                        json.loads(acquire_response["payload"])["result"]["structuredContent"],
                    )

                    _send_frame(
                        client,
                        {
                            "type": "close",
                            "sessionId": "webrtc-session-a",
                            "reason": "data channel closed",
                        },
                    )
                    deadline = time.monotonic() + 2.0
                    while not cmd_vel.stop_reasons and time.monotonic() < deadline:
                        time.sleep(0.01)
            finally:
                ipc_server.stop()

        self.assertIn("data channel closed", cmd_vel.stop_reasons)


if __name__ == "__main__":
    unittest.main()
