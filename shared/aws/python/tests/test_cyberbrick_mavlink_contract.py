from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
BOARD_DIR = REPO_ROOT / "devices" / "common" / "board"
DEVICE_DIRS = {
    "cyberbrick": REPO_ROOT / "devices" / "cyberbrick",
    "tbot": REPO_ROOT / "devices" / "tbot",
}


class SchemaValidationError(ValueError):
    pass


class ContractSchemaValidator:
    """Small draft-2020 subset for checked-in contract fixtures.

    The schemas remain standard JSON Schema documents for runtime consumers. This
    verifier intentionally covers the keywords used by this repository's
    contract schemas without adding a Python package to production tooling.
    """

    def __init__(self, schema_file: Path) -> None:
        self._schemas: dict[Path, dict[str, Any]] = {}
        self._root_file = schema_file.resolve()

    def validate(self, instance: Any) -> None:
        self._validate(instance, self._load(self._root_file), self._root_file, "$")

    def _load(self, file: Path) -> dict[str, Any]:
        if file not in self._schemas:
            payload = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise SchemaValidationError(f"{file} must contain an object schema")
            self._schemas[file] = payload
        return self._schemas[file]

    def _resolve_ref(self, ref: str, file: Path) -> tuple[dict[str, Any], Path]:
        target_file_text, separator, fragment = ref.partition("#")
        target_file = (file.parent / target_file_text).resolve() if target_file_text else file
        target: Any = self._load(target_file)
        if separator and fragment:
            for token in fragment.removeprefix("/").split("/"):
                if not token:
                    continue
                target = target[token.replace("~1", "/").replace("~0", "~")]
        if not isinstance(target, dict):
            raise SchemaValidationError(f"{ref} does not resolve to an object schema")
        return target, target_file

    def _validate(self, value: Any, schema: dict[str, Any], file: Path, path: str) -> None:
        if "$ref" in schema:
            target, target_file = self._resolve_ref(str(schema["$ref"]), file)
            self._validate(value, target, target_file, path)
            return
        if "oneOf" in schema:
            matches = 0
            for candidate in schema["oneOf"]:
                try:
                    self._validate(value, candidate, file, path)
                except SchemaValidationError:
                    continue
                matches += 1
            if matches != 1:
                raise SchemaValidationError(f"{path} must match exactly one oneOf branch")
            return
        if "const" in schema and value != schema["const"]:
            raise SchemaValidationError(f"{path} must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            raise SchemaValidationError(f"{path} must be one of {schema['enum']!r}")
        expected_types = schema.get("type")
        if expected_types is not None:
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            if not any(self._matches_type(value, expected) for expected in expected_types):
                raise SchemaValidationError(f"{path} has an invalid type")
        if isinstance(value, dict):
            required = schema.get("required", [])
            for key in required:
                if key not in value:
                    raise SchemaValidationError(f"{path}.{key} is required")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                extras = set(value).difference(properties)
                if extras:
                    raise SchemaValidationError(f"{path} contains unexpected properties {sorted(extras)!r}")
            for key, child in properties.items():
                if key in value:
                    self._validate(value[key], child, file, f"{path}.{key}")
        if isinstance(value, list) and "items" in schema:
            for index, item in enumerate(value):
                self._validate(item, schema["items"], file, f"{path}[{index}]")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                raise SchemaValidationError(f"{path} is too short")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                raise SchemaValidationError(f"{path} is too long")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                raise SchemaValidationError(f"{path} does not match {schema['pattern']!r}")
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                raise SchemaValidationError(f"{path} is below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                raise SchemaValidationError(f"{path} is above maximum")
            if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
                raise SchemaValidationError(f"{path} is below exclusive minimum")

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None,
        }.get(expected, False)


def load_json(device: str, relative_path: str) -> Any:
    return json.loads((DEVICE_DIRS[device] / relative_path).read_text(encoding="utf-8"))


class BoardMavlinkContractTests(unittest.TestCase):
    def test_device_owned_descriptor_status_and_shadow_fixtures_match_schemas(self) -> None:
        cases = (
            ("aws/mavlink-descriptor.schema.json", "aws/fixtures/mavlink-descriptor.json"),
            ("aws/mavlink-status.schema.json", "aws/fixtures/mavlink-status.json"),
            ("aws/mavlink-shadow.schema.json", "aws/default-mavlink-shadow.json"),
            ("aws/mavlink-shadow.schema.json", "aws/fixtures/mavlink-shadow.json"),
        )
        for device, device_dir in DEVICE_DIRS.items():
            for schema_path, fixture_path in cases:
                with self.subTest(device=device, fixture=fixture_path):
                    ContractSchemaValidator(device_dir / schema_path).validate(load_json(device, fixture_path))

    def test_status_and_shadow_reject_generic_timestamps(self) -> None:
        for device, device_dir in DEVICE_DIRS.items():
            with self.subTest(device=device, contract="status"):
                status = load_json(device, "aws/fixtures/mavlink-status.json")
                status["updatedAtMs"] = 123
                with self.assertRaisesRegex(SchemaValidationError, "unexpected"):
                    ContractSchemaValidator(device_dir / "aws/mavlink-status.schema.json").validate(status)

            with self.subTest(device=device, contract="shadow"):
                shadow = load_json(device, "aws/fixtures/mavlink-shadow.json")
                shadow["state"]["reported"]["observedAtMs"] = 123
                with self.assertRaisesRegex(SchemaValidationError, "unexpected"):
                    ContractSchemaValidator(device_dir / "aws/mavlink-shadow.schema.json").validate(shadow)

    def test_control_envelopes_require_stable_requests_responses_and_errors(self) -> None:
        validator = ContractSchemaValidator(BOARD_DIR / "protocol/mavlink-webrtc.schema.json")
        validator.validate({"type": "control.get_state", "requestId": "state-1"})
        validator.validate(
            {"type": "control.activate", "requestId": "activate-1", "actor": "operator", "takeover": False}
        )
        validator.validate({"type": "control.renew_active", "requestId": "renew-1", "epoch": 4})
        validator.validate({"type": "control.release_active", "requestId": "release-1", "epoch": 4})
        validator.validate(
            {
                "type": "control.activated",
                "requestId": "activate-1",
                "state": {
                    "epoch": 4,
                    "leaseTtlMs": 5000,
                    "activeControl": {"sessionId": "peer-a", "actor": "operator", "epoch": 4},
                },
            }
        )
        validator.validate(
            {"type": "control.error", "requestId": "renew-1", "code": "stale_epoch"}
        )
        invalid = {
            "type": "control.error",
            "requestId": "renew-1",
            "code": "new_unstable_error_code",
        }
        with self.assertRaises(SchemaValidationError):
            validator.validate(invalid)

    def test_protocol_sources_define_the_documented_services(self) -> None:
        mavlink_proto = (BOARD_DIR / "proto/txing/board/mavlink/v1/mavlink.proto").read_text(encoding="utf-8")
        bridge_proto = (BOARD_DIR / "proto/txing/board/mavlink_bridge/v1/mavlink_bridge.proto").read_text(encoding="utf-8")
        for method in ("GetStatus", "Exchange", "EnterSafeState"):
            self.assertIn(method, mavlink_proto)
        self.assertIn("package txing.board.mavlink.v1;", mavlink_proto)
        for method in (
            "GetControlChannelConfig",
            "RefreshControlChannelCredentials",
            "OpenPeer",
            "HandleControlMessage",
            "ExchangeFrames",
            "ClosePeer",
        ):
            self.assertIn(method, bridge_proto)
        self.assertIn("authority for session identity", bridge_proto)

    def test_device_descriptors_preserve_the_shared_wire_contract(self) -> None:
        for device in DEVICE_DIRS:
            with self.subTest(device=device):
                descriptor = load_json(device, "aws/fixtures/mavlink-descriptor.json")
                self.assertEqual(descriptor["serviceId"], "mavlink")
                self.assertEqual(descriptor["dataChannel"], {
                    "label": "txing.mavlink.v1",
                    "ordered": True,
                    "reliable": True,
                    "binaryMessage": "mavlink2-unsigned-common-frame",
                    "textMessage": "cyberbrick-mavlink-control-json-v1",
                })


if __name__ == "__main__":
    unittest.main()
