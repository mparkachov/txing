from __future__ import annotations

from pathlib import Path
import unittest

from aws.device_catalog import load_device_manifest
from rig.device_process import (
    DeviceProcessError,
    build_device_process_environment,
    build_device_process_invocation,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class DeviceProcessContractTests(unittest.TestCase):
    def test_generic_rig_sources_do_not_import_unit_runtime(self) -> None:
        rig_src = REPO_ROOT / "rig" / "src" / "rig"
        source_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(rig_src.glob("*.py"))
        )

        self.assertNotIn("unit_rig", source_text)

    def test_builds_invocation_from_manifest_without_importing_device_runtime(self) -> None:
        manifest = load_device_manifest("unit", repo_root=REPO_ROOT)
        base_environment = {
            "RIG_NAME": "rig",
            "THING_NAME": "unit-local",
            "SPARKPLUG_GROUP_ID": "town",
            "SPARKPLUG_EDGE_NODE_ID": "rig",
            "AWS_REGION": "eu-central-1",
        }

        invocation = build_device_process_invocation(
            manifest,
            "unit-connectivity-ble",
            base_environment=base_environment,
        )

        self.assertEqual(invocation.device_type, "unit")
        self.assertEqual(invocation.process_name, "unit-connectivity-ble")
        self.assertEqual(invocation.argv, ("uv", "run", "--project", "rig/python", "unit-rig-connectivity-ble"))
        self.assertEqual(invocation.cwd, REPO_ROOT / "devices" / "unit")
        self.assertEqual(invocation.env["TXING_DEVICE_TYPE"], "unit")
        self.assertEqual(
            invocation.env["TXING_DEVICE_MANIFEST"],
            str(REPO_ROOT / "devices" / "unit" / "manifest.toml"),
        )

    def test_reports_missing_required_process_environment(self) -> None:
        manifest = load_device_manifest("unit", repo_root=REPO_ROOT)

        with self.assertRaisesRegex(DeviceProcessError, "RIG_NAME"):
            build_device_process_invocation(
                manifest,
                "unit-connectivity-ble",
                base_environment={
                    "THING_NAME": "unit-local",
                    "SPARKPLUG_GROUP_ID": "town",
                    "SPARKPLUG_EDGE_NODE_ID": "rig",
                    "AWS_REGION": "eu-central-1",
                },
            )

    def test_environment_adds_device_contract_paths(self) -> None:
        manifest = load_device_manifest("unit", repo_root=REPO_ROOT)

        env = build_device_process_environment(manifest, base_environment={})

        self.assertEqual(env["TXING_DEVICE_TYPE"], "unit")
        self.assertEqual(env["TXING_DEVICE_DIR"], str(REPO_ROOT / "devices" / "unit"))
        self.assertEqual(
            env["TXING_DEVICE_MANIFEST"],
            str(REPO_ROOT / "devices" / "unit" / "manifest.toml"),
        )


if __name__ == "__main__":
    unittest.main()
