"""Local C++ host protocol tests. The fixture never calls AWS or a device."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class WebSocket:
    def __init__(self, port_number, path="/stream"):
        self.socket = socket.create_connection(("127.0.0.1", port_number), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                             f"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n"
                             "Sec-WebSocket-Protocol: txing.agent.probe.v1\r\n\r\n").encode())
        headers = bytearray()
        try:
            while not headers.endswith(b"\r\n\r\n"):
                headers.extend(self.exact(1))
        except EOFError:
            self.accepted = False
            return
        self.accepted = headers.startswith(b"HTTP/1.1 101")
        if self.accepted:
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            assert expected in headers

    def exact(self, size):
        result = bytearray()
        while len(result) < size:
            data = self.socket.recv(size - len(result))
            if not data:
                raise EOFError("WebSocket closed")
            result.extend(data)
        return bytes(result)

    def send(self, data, opcode=1, final=True):
        mask = os.urandom(4)
        length = len(data)
        header = bytes([(0x80 if final else 0) | opcode])
        header += bytes([0x80 | length]) if length < 126 else bytes([0x80 | 126]) + struct.pack("!H", length)
        self.socket.sendall(header + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(data)))

    def receive(self):
        first, second = self.exact(2)
        length = second & 127
        if length == 126:
            length = struct.unpack("!H", self.exact(2))[0]
        if length == 127:
            length = struct.unpack("!Q", self.exact(8))[0]
        return first & 15, self.exact(length)

    def close(self):
        self.socket.close()


class MicrovmHostTests(unittest.TestCase):
    def setUp(self):
        self.hooks, self.ingress = port(), port()
        while self.hooks == self.ingress:
            self.ingress = port()
        self.process = subprocess.Popen([str(ROOT / "tmp/agent-build/agent-host-tests"), "--serve", str(self.hooks), str(self.ingress)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while True:
            try:
                self.request(self.ingress, "/status")
                break
            except (OSError, http.client.HTTPException):
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    self.fail("C++ fixture did not start")
                time.sleep(0.02)

    def tearDown(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            self.fail("C++ host did not stop")
        finally:
            self.process.stderr.close()

    @staticmethod
    def request(port_number, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port_number, timeout=3)
        try:
            connection.request("POST" if body is not None else "GET", path, body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def run_hook(self):
        payload = json.dumps({"microvmId": "mvm-fixture", "runHookPayload": json.dumps({"thingId": "tbot-fixture", "region": "eu-central-1"})})
        return self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/run", payload)

    def test_hook_isolation_and_post_restore_start(self):
        status, initial = self.request(self.ingress, "/status")
        self.assertEqual((status, initial["phase"], initial["credentials"]), (200, "waiting-for-run", {}))
        self.assertEqual(self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/ready", "")[0], 200)
        self.assertEqual(self.request(self.ingress, "/aws/lambda-microvms/runtime/v1/run", "{}")[0], 404)
        self.assertEqual(self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/run", "{}")[0], 400)
        self.assertEqual(self.run_hook()[0], 200)
        self.assertEqual(self.run_hook()[0], 200)
        self.assertEqual(self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/ready", "")[0], 409)
        self.assertEqual(self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/terminate", "")[0], 200)
        self.assertEqual(self.run_hook()[0], 409)

    def test_cloud_hook_rejects_expired_and_oversized_deadlines_over_http(self):
        hooks, ingress = port(), port()
        while hooks == ingress or hooks in (self.hooks, self.ingress) or ingress in (self.hooks, self.ingress):
            hooks, ingress = port(), port()
        environment = dict(os.environ)
        environment.update({"AWS_EC2_METADATA_DISABLED": "true",
                            "AWS_CONFIG_FILE": str(ROOT / "tmp/agent-test/no-config"),
                            "AWS_SHARED_CREDENTIALS_FILE": str(ROOT / "tmp/agent-test/no-credentials")})
        process = subprocess.Popen([str(ROOT / "tmp/agent-build/agent-host-tests"), "--serve-cloud", str(hooks), str(ingress)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment)
        try:
            limit = time.monotonic() + 5
            while True:
                try:
                    self.request(ingress, "/status")
                    break
                except (OSError, http.client.HTTPException):
                    if process.poll() is not None or time.monotonic() >= limit:
                        self.fail("cloud host fixture did not start")
                    time.sleep(0.02)
            def request_run(deadline):
                payload = json.dumps({"microvmId": "mvm-fixture", "runHookPayload": json.dumps({
                    "thingId": "tbot-fixture", "region": "eu-central-1", "runId": "run-1",
                    "activationId": "activation-1", "deadline": str(deadline)})})
                return self.request(hooks, "/aws/lambda-microvms/runtime/v1/run", payload)
            self.assertEqual(request_run(1)[0], 409)
            self.assertEqual(request_run(int(time.time()) + 6000)[0], 400)
            self.assertEqual(self.request(ingress, "/status")[1]["phase"], "waiting-for-run")
            self.assertEqual(request_run(int(time.time()) + 60)[0], 200)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stderr.close()

    def test_websocket_binary_text_fragments_and_exclusivity(self):
        self.run_hook()
        stream = WebSocket(self.ingress)
        self.addCleanup(stream.close)
        self.assertTrue(stream.accepted)
        other = WebSocket(self.ingress)
        self.addCleanup(other.close)
        self.assertFalse(other.accepted)
        hooks = WebSocket(self.hooks)
        self.addCleanup(hooks.close)
        self.assertFalse(hooks.accepted)
        stream.send(b'{"type":', final=False)
        stream.send(b'"ping"}', opcode=0)
        stream.send(bytes([0xFD, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0]), opcode=2)
        received = set()
        deadline = time.monotonic() + 3
        while len(received) < 3 and time.monotonic() < deadline:
            opcode, data = stream.receive()
            if opcode == 2:
                self.assertEqual(data[0], 0xFD)
                received.add("telemetry")
            elif opcode == 1:
                result = json.loads(data)
                if result.get("type") == "send.result":
                    self.assertFalse(result["accepted"])
                    received.add("unauthorized-frame")
                elif result.get("type") == "pong":
                    received.add("pong")
        self.assertEqual(received, {"telemetry", "unauthorized-frame", "pong"})

    def test_oversized_websocket_closes_connection(self):
        self.run_hook()
        stream = WebSocket(self.ingress)
        self.addCleanup(stream.close)
        self.assertTrue(stream.accepted)
        stream.send(b"x" * 4097)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                opcode, _ = stream.receive()
                if opcode == 8:
                    return
            except (EOFError, ConnectionError):
                return
        self.fail("oversized message did not close connection")

    def test_oversized_hook_never_starts_a_runtime(self):
        payload = json.dumps({"microvmId": "mvm-fixture", "runHookPayload": json.dumps({"thingId": "tbot-fixture", "region": "eu-central-1"})})
        self.assertEqual(self.request(self.hooks, "/aws/lambda-microvms/runtime/v1/run", payload + " " * 20000)[0], 413)
        self.assertEqual(self.request(self.ingress, "/status")[1]["phase"], "waiting-for-run")

    def test_production_build_hooks_do_not_read_aws_profiles(self):
        # A profile read would block on these FIFOs. Exercise the production
        # executable, not the fake runner, before any /run hook is delivered.
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            config = Path(directory) / "config-fifo"
            credentials = Path(directory) / "credentials-fifo"
            os.mkfifo(config, 0o600)
            os.mkfifo(credentials, 0o600)
            hooks, ingress = port(), port()
            while ingress == hooks:
                ingress = port()
            environment = dict(os.environ, AWS_CONFIG_FILE=str(config),
                               AWS_SHARED_CREDENTIALS_FILE=str(credentials))
            process = subprocess.Popen([str(ROOT / "tmp/agent-build/txing-agent"), "--microvm",
                                        "--ca", str(ROOT / "agent/probe/hooks.json"),
                                        "--hook-port", str(hooks), "--attachment-port", str(ingress)],
                                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while True:
                    try:
                        status, data = self.request(ingress, "/status")
                        break
                    except (OSError, http.client.HTTPException):
                        self.assertIsNone(process.poll(), "production host exited before readiness")
                        self.assertLess(time.monotonic(), deadline, "build phase attempted AWS profile reads")
                        time.sleep(0.02)
                self.assertEqual((status, data["phase"], data["credentials"]), (200, "waiting-for-run", {}))
                for hook in ("ready", "validate"):
                    self.assertEqual(self.request(hooks, "/aws/lambda-microvms/runtime/v1/" + hook, "")[0], 200)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    self.fail("production host could not stop before /run")
                finally:
                    process.stderr.close()
            self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
