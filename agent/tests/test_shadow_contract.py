"""Contract examples and forbidden states; no AWS calls or runtime claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
AWS = ROOT / "devices/tbot/aws"


def load(name):
    return json.loads((AWS / name).read_text())


class AgentShadowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = load("agent-shadow.schema.json")
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def assertValid(self, payload):
        self.validator.validate(payload)

    def assertInvalid(self, payload):
        self.assertFalse(self.validator.is_valid(payload))

    def test_default_and_iot_null_deletion_representation(self):
        self.assertValid(load("default-agent-shadow.json"))
        self.assertValid({"state": {"reported": {"lifecycle": {"state": "stopped"}}}})

    def test_running_example_keeps_independent_diagnostics(self):
        payload = load("fixtures/agent-shadow.json")
        self.assertValid(payload)
        reported = payload["state"]["reported"]
        self.assertEqual(reported["run"]["id"], reported["runtime"]["runId"])
        self.assertEqual(reported["activation"]["deadline"] - reported["activation"]["startedAt"], 3000)
        self.assertEqual(reported["runtime"]["mavlink"]["state"], "connected")
        self.assertEqual(reported["runtime"]["video"]["state"], "error")
        reported["runtime"]["mavlink"] = {"state": "error", "lastError": "mavlink: ICE failed"}
        reported["runtime"]["video"]["state"] = "connected"
        reported["runtime"]["control"]["state"] = "lost"
        self.assertValid(payload)

    def test_starting_reserves_identity_before_hosting_id_is_known(self):
        payload = load("fixtures/agent-shadow.json")
        reported = payload["state"]["reported"]
        reported["lifecycle"]["state"] = "starting"
        for key in ("endpoint", "runtime"):
            reported.pop(key)
        reported["run"].pop("microvmId")
        self.assertValid(payload)
        for key in ("run", "activation"):
            broken = deepcopy(payload)
            broken["state"]["reported"].pop(key)
            self.assertInvalid(broken)
        reported["lifecycle"].pop("verifiedAt")
        self.assertInvalid(payload)

    def test_endpoint_requires_current_running_cloud_identity(self):
        for state in ("stopped", "starting", "stopping", "expired", "error"):
            with self.subTest(state=state):
                payload = load("fixtures/agent-shadow.json")
                payload["state"]["reported"]["lifecycle"]["state"] = state
                self.assertInvalid(payload)
                payload["state"]["reported"]["endpoint"] = None
                self.assertValid(payload)
        payload = load("fixtures/agent-shadow.json")
        payload["state"]["reported"]["run"].pop("microvmId")
        self.assertInvalid(payload)

    def test_no_raw_udp_or_credential_bearing_endpoint(self):
        for endpoint in ({"ipv4": "192.0.2.1", "udpPort": 14550}, "http://example.invalid", "wss://example.invalid", "https://user:secret@example.invalid", "https://example.invalid/?token=secret", "https://example.invalid/#token"):
            with self.subTest(endpoint=endpoint):
                payload = load("fixtures/agent-shadow.json")
                payload["state"]["reported"]["endpoint"] = endpoint
                self.assertInvalid(payload)

    def test_expiry_retains_activation_without_advertising_an_endpoint(self):
        payload = load("default-agent-shadow.json")
        reported = payload["state"]["reported"]
        reported["lifecycle"]["state"] = "expired"
        self.assertInvalid(payload)
        reported["activation"] = load("fixtures/agent-shadow.json")["state"]["reported"]["activation"]
        self.assertValid(payload)

    def test_sample_requires_run_identity_timestamp_and_both_sessions(self):
        for key in ("runId", "sampledAt", "mavlink", "video", "control"):
            with self.subTest(key=key):
                payload = load("fixtures/agent-shadow.json")
                payload["state"]["reported"]["runtime"].pop(key)
                self.assertInvalid(payload)
        payload = load("fixtures/agent-shadow.json")
        reported = payload["state"]["reported"]
        reported["lifecycle"]["state"] = "stopped"
        reported.pop("endpoint")
        reported.pop("run")
        self.assertInvalid(payload)

    def test_rejects_invalid_runtime_counters_states_and_release(self):
        for path, value in (("run.release", "latest"), ("runtime.video.framesReceived", -1), ("runtime.video.lastFrameAt", -1), ("runtime.sampledAt", -1), ("runtime.control.state", "armed"), ("runtime.mavlink.state", "ready")):
            with self.subTest(path=path):
                payload = load("fixtures/agent-shadow.json")
                node = payload["state"]["reported"]
                *parents, key = path.split(".")
                for parent in parents:
                    node = node[parent]
                node[key] = value
                self.assertInvalid(payload)

    def test_no_legacy_fields_or_desired_command_interface(self):
        payload = load("default-agent-shadow.json")
        payload["state"]["reported"]["task"] = {"id": None, "status": "stopped"}
        self.assertInvalid(payload)
        payload = load("default-agent-shadow.json")
        payload["state"]["desired"] = {"control": "held"}
        self.assertInvalid(payload)

    def test_controller_bookkeeping_has_bounded_launch_request(self):
        payload = load("default-agent-shadow.json")
        payload["state"]["reported"]["controller"] = {
            "projectionVersion": 2, "sourceTimestampMs": 1000,
            "inactiveObservedAt": 10, "observed": True, "active": False,
        }
        self.assertValid(payload)
        controller = payload["state"]["reported"]["controller"]
        controller["unverifiedSince"] = 12
        self.assertValid(payload)
        controller["unverifiedSince"] = -1
        self.assertInvalid(payload)
        controller.pop("unverifiedSince")
        controller["stopRequestedAt"] = 12
        self.assertValid(payload)
        controller["stopRequestedAt"] = -1
        self.assertInvalid(payload)
        controller.pop("stopRequestedAt")
        controller["launchRequest"] = "x" * 2049
        self.assertInvalid(payload)
        controller.pop("launchRequest")
        controller["secret"] = "not allowed"
        self.assertInvalid(payload)

    def test_iot_response_envelope_is_accepted(self):
        payload = load("fixtures/agent-shadow.json")
        payload["metadata"] = {"reported": {"endpoint": {"timestamp": 1792281660}}}
        payload["clientToken"] = "controller-write"
        self.assertValid(payload)


if __name__ == "__main__":
    unittest.main()
