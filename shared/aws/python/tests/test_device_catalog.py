from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from aws.device_catalog import (
    DeviceTypeNotFoundError,
    discover_repo_root,
    list_loadable_device_types,
    load_device_manifest,
)
from aws.thing_capabilities import capabilities_for_thing_type, load_thing_type_capabilities


REPO_ROOT = Path(__file__).resolve().parents[4]


class DeviceCatalogTests(unittest.TestCase):
    def test_discovers_repo_root_from_test_file(self) -> None:
        self.assertEqual(discover_repo_root(Path(__file__)), REPO_ROOT)

    def test_lists_only_loadable_device_types(self) -> None:
        self.assertEqual(list_loadable_device_types(repo_root=REPO_ROOT), ["unit"])

    def test_loads_unit_manifest(self) -> None:
        manifest = load_device_manifest("unit", repo_root=REPO_ROOT)

        self.assertEqual(manifest.type, "unit")
        self.assertEqual(manifest.device_name, "bot")
        self.assertEqual(manifest.display_name, "Bot")
        self.assertEqual(
            manifest.capabilities,
            ("sparkplug", "mcu", "board", "mcp", "video"),
        )
        self.assertEqual(
            manifest.shadow_schema,
            REPO_ROOT / "devices" / "unit" / "aws" / "sparkplug-shadow.schema.json",
        )
        self.assertEqual(
            manifest.default_shadow,
            REPO_ROOT / "devices" / "unit" / "aws" / "default-sparkplug-shadow.json",
        )
        self.assertEqual(
            manifest.render_board_video_channel_name(device_id="unit-a7k2p9"),
            "unit-a7k2p9-board-video",
        )
        self.assertEqual(
            manifest.shadow_contract("board").default,
            REPO_ROOT / "devices" / "unit" / "aws" / "default-board-shadow.json",
        )
        self.assertEqual(
            [process.name for process in manifest.rig_processes],
            ["unit-connectivity-ble", "unit-sparkplug-manager"],
        )
        self.assertEqual(manifest.rig_processes[0].argv[:4], ("uv", "run", "--project", "rig/python"))
        self.assertEqual(manifest.web_adapter, "web/unit-adapter.tsx")

    def test_template_is_not_loadable(self) -> None:
        with self.assertRaises(DeviceTypeNotFoundError):
            load_device_manifest("template", repo_root=REPO_ROOT)

    def test_capabilities_merge_shared_types_and_device_manifests(self) -> None:
        capabilities = load_thing_type_capabilities(repo_root=REPO_ROOT)

        self.assertEqual(capabilities["town"], ("sparkplug",))
        self.assertEqual(capabilities["rig"], ("sparkplug",))
        self.assertEqual(
            capabilities["unit"],
            ("sparkplug", "mcu", "board", "mcp", "video"),
        )
        self.assertEqual(
            capabilities_for_thing_type("unit", repo_root=REPO_ROOT),
            ("sparkplug", "mcu", "board", "mcp", "video"),
        )

    def test_manifest_capabilities_are_device_defined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "justfile").write_text("\n", encoding="utf-8")
            device_dir = repo_root / "devices" / "sensor"
            aws_dir = device_dir / "aws"
            aws_dir.mkdir(parents=True)
            for name in ("sparkplug", "sensor-data"):
                (aws_dir / f"{name}-shadow.schema.json").write_text(
                    json.dumps({"type": "object"}),
                    encoding="utf-8",
                )
                (aws_dir / f"default-{name}-shadow.json").write_text(
                    json.dumps({"state": {"reported": {}}}),
                    encoding="utf-8",
                )
            (device_dir / "web").mkdir()
            (device_dir / "web" / "sensor-adapter.tsx").write_text(
                "export default {}\n",
                encoding="utf-8",
            )
            (device_dir / "manifest.toml").write_text(
                """
type = "sensor"
device_name = "sensor"
display_name = "Sensor"
capabilities = ["sparkplug", "sensor-data"]

[shadows.sparkplug]
schema = "aws/sparkplug-shadow.schema.json"
default = "aws/default-sparkplug-shadow.json"

[shadows.sensor-data]
schema = "aws/sensor-data-shadow.schema.json"
default = "aws/default-sensor-data-shadow.json"

[web]
adapter = "web/sensor-adapter.tsx"
""".strip(),
                encoding="utf-8",
            )

            manifest = load_device_manifest("sensor", repo_root=repo_root)

        self.assertEqual(manifest.capabilities, ("sparkplug", "sensor-data"))
        self.assertEqual(manifest.shadow_contract("sensor-data").name, "sensor-data")


if __name__ == "__main__":
    unittest.main()
