"""Real native executable argument/bind failures; never contacts AWS/devices."""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "tmp/agent-build/txing-agent"


class ManualCliTests(unittest.TestCase):
    def invoke(self, *args, env=None):
        return subprocess.run([str(BINARY), *args], capture_output=True, text=True,
                              timeout=3, env=env, cwd=ROOT)

    def test_help_describes_default_ports_and_explicit_control(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0)
        for text in ("[udp-port]", "[--control]", "127.0.0.1:14551", "127.0.0.1:14550", "observation by default"):
            self.assertIn(text, result.stdout)

    def test_invalid_ports_fail_before_ca_credentials_or_network(self):
        for value in ("0", "65536", "-1", "abc", "1.5", "99999999999999999999"):
            with self.subTest(value=value):
                result = self.invoke("fixture", value, "--control")
                self.assertEqual(result.returncode, 2)
                self.assertIn("UDP port must be an integer from 1 to 65535", result.stderr)
        result = self.invoke("fixture", "--qgc-port", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("UDP port", result.stderr)

    def test_occupied_port_precedes_sdk_configuration_reads(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="manual-cli-") as directory:
            # Any accidental AWS configuration read would block and fail the
            # subprocess deadline instead of performing a real API request.
            config, credentials = Path(directory) / "config", Path(directory) / "credentials"
            os.mkfifo(config)
            os.mkfifo(credentials)
            env = {**os.environ, "AWS_CONFIG_FILE": str(config),
                   "AWS_SHARED_CREDENTIALS_FILE": str(credentials), "AWS_EC2_METADATA_DISABLED": "true"}
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
                occupied.bind(("127.0.0.1", 0))
                port = occupied.getsockname()[1]
                result = self.invoke("fixture", str(port), "--control", "--ca",
                                     str(ROOT / "agent/probe/hooks.json"), env=env)
                self.assertEqual(result.returncode, 2)
                self.assertIn(f"bind 127.0.0.1:{port}", result.stderr)
                self.assertIn("choose another [udp-port]", result.stderr)

    def test_endpoint_cannot_be_the_listener(self):
        result = self.invoke("fixture", "16051", "--qgc-port", "16051", "--ca",
                             str(ROOT / "agent/probe/hooks.json"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("must use different UDP ports", result.stderr)
