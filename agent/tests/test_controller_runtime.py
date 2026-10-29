"""Exercise the custom Lambda runtime locally without any AWS requests."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RuntimeFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/2018-06-01/runtime/invocation/next" or self.server.delivered:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.server.delivered = True
        body = self.server.event
        self.send_response(200)
        self.send_header("Lambda-Runtime-Aws-Request-Id", "request-1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        self.server.result = (self.path, self.headers.get("Content-Type"), self.rfile.read(size))
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()


class ControllerRuntimeTests(unittest.TestCase):
    def run_fixture(self, automation, image="", event=b'{"source":"aws.events"}'):
        server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeFixture)
        server.daemon_threads = True
        server.delivered, server.result = False, None
        server.event = event
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = dict(os.environ)
        environment.update({
            "AWS_LAMBDA_RUNTIME_API": f"127.0.0.1:{server.server_port}",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_CONFIG_FILE": str(ROOT / "tmp/agent-test/no-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(ROOT / "tmp/agent-test/no-credentials"),
            "TXING_AGENT_AUTOMATION": automation,
            "TXING_AGENT_IMAGE": image, "TXING_AGENT_IMAGE_VERSION": "",
            "TXING_AGENT_EXECUTION_ROLE": "", "TXING_AGENT_LOG_GROUP": "", "TXING_AGENT_RELEASE": "",
        })
        try:
            process = subprocess.run([str(ROOT / "tmp/agent-build/txing-agent-controller")], env=environment,
                                     capture_output=True, timeout=10, check=False)
            self.assertIsNotNone(server.result, process.stderr.decode(errors="replace"))
            return server.result
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_disabled_automation_acknowledges_without_aws_configuration(self):
        path, content_type, body = self.run_fixture("disabled", "arn:aws:lambda:eu-central-1:123456789012:microvm-image:disabled")
        self.assertEqual(path, "/2018-06-01/runtime/invocation/request-1/response")
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(body), {"ok": True})

    def test_enabled_without_artifacts_fails_closed(self):
        path, content_type, body = self.run_fixture("enabled", "arn:aws:lambda:eu-central-1:123456789012:microvm-image:disabled")
        self.assertEqual(path, "/2018-06-01/runtime/invocation/request-1/error")
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(body)["errorType"], "AgentControllerError")

    def test_invalid_automation_reports_configuration_error(self):
        for setting in ("", "invalid"):
            with self.subTest(setting=setting):
                path, content_type, body = self.run_fixture(setting, "arn:aws:lambda:eu-central-1:123456789012:microvm-image:disabled")
                self.assertTrue(path.endswith("/error"))
                self.assertEqual(content_type, "application/json")
                self.assertEqual(json.loads(body)["errorType"], "AgentControllerError")

    def test_disabled_placeholder_and_queued_lifecycle_do_not_contact_aws(self):
        path, _, body = self.run_fixture("disabled", "arn:aws:lambda:eu-central-1:123456789012:microvm-image:disabled")
        self.assertTrue(path.endswith("/response"))
        self.assertEqual(json.loads(body), {"ok": True})
        path, _, body = self.run_fixture("disabled", "arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent",
                                         b'{"thingName":"tbot-test"}')
        self.assertTrue(path.endswith("/response"))
        self.assertEqual(json.loads(body), {"ok": True})


if __name__ == "__main__":
    unittest.main()
