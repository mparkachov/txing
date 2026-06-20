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
        self.assertEqual(
            list_loadable_device_types(repo_root=REPO_ROOT),
            ["cloud-mcu", "power", "power-si", "unit", "weather"],
        )

    def test_loads_unit_manifest(self) -> None:
        manifest = load_device_manifest("unit", repo_root=REPO_ROOT)

        self.assertEqual(manifest.type, "unit")
        self.assertEqual(manifest.device_name, "bot")
        self.assertEqual(manifest.display_name, "Bot")
        self.assertEqual(
            manifest.capabilities,
            ("sparkplug", "ble", "power", "board", "mcp", "video"),
        )
        self.assertEqual(manifest.compatible_rig_types, ("raspi",))
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
        self.assertEqual(manifest.web_adapter, "web/unit-adapter.tsx")

    def test_loads_cloud_mcu_manifest(self) -> None:
        manifest = load_device_manifest("cloud-mcu", repo_root=REPO_ROOT)

        self.assertEqual(manifest.type, "cloud-mcu")
        self.assertEqual(manifest.device_name, "cloud")
        self.assertEqual(manifest.display_name, "Cloud MCU")
        self.assertEqual(manifest.capabilities, ("sparkplug", "sqs", "power", "ecs"))
        self.assertEqual(manifest.compatible_rig_types, ("cloud",))
        self.assertEqual(
            [contract.name for contract in manifest.shadows.values()],
            ["sparkplug", "sqs", "power", "ecs"],
        )
        self.assertEqual(manifest.render_board_video_channel_name(device_id="cloud"), None)
        self.assertEqual(manifest.web_adapter, "web/cloud-mcu-adapter.tsx")
        for shadow_name in ("sparkplug", "sqs", "power", "ecs"):
            contract = manifest.shadow_contract(shadow_name)
            self.assertIsInstance(json.loads(contract.schema.read_text(encoding="utf-8")), dict)
            self.assertIsInstance(json.loads(contract.default.read_text(encoding="utf-8")), dict)

    def test_loads_weather_manifest(self) -> None:
        manifest = load_device_manifest("weather", repo_root=REPO_ROOT)

        self.assertEqual(manifest.type, "weather")
        self.assertEqual(manifest.device_name, "outside")
        self.assertEqual(manifest.display_name, "Weather")
        self.assertEqual(manifest.capabilities, ("sparkplug", "ble", "power", "weather"))
        self.assertEqual(manifest.compatible_rig_types, ("raspi",))
        self.assertEqual(manifest.render_board_video_channel_name(device_id="outside"), None)
        self.assertEqual(manifest.web_adapter, "web/weather-adapter.tsx")

    def test_loads_power_si_manifest(self) -> None:
        manifest = load_device_manifest("power-si", repo_root=REPO_ROOT)

        self.assertEqual(manifest.type, "power-si")
        self.assertEqual(manifest.device_name, "power-si")
        self.assertEqual(manifest.display_name, "Power SI")
        self.assertEqual(manifest.capabilities, ("sparkplug", "thread", "power"))
        self.assertEqual(manifest.compatible_rig_types, ("raspi",))
        self.assertEqual(manifest.redcon_command_levels, (4, 3))
        self.assertEqual(
            manifest.redcon_rules,
            {
                3: ("sparkplug", "thread", "power"),
                4: ("sparkplug", "thread"),
            },
        )
        self.assertEqual(
            [contract.name for contract in manifest.shadows.values()],
            ["sparkplug", "thread", "power"],
        )
        self.assertEqual(manifest.render_board_video_channel_name(device_id="power-si-a1"), None)
        self.assertEqual(manifest.web_adapter, "web/power-si-adapter.tsx")
        for shadow_name in ("sparkplug", "thread", "power"):
            contract = manifest.shadow_contract(shadow_name)
            self.assertIsInstance(json.loads(contract.schema.read_text(encoding="utf-8")), dict)
            self.assertIsInstance(json.loads(contract.default.read_text(encoding="utf-8")), dict)

    def test_template_is_not_loadable(self) -> None:
        with self.assertRaises(DeviceTypeNotFoundError):
            load_device_manifest("template", repo_root=REPO_ROOT)

    def test_capabilities_merge_shared_types_and_device_manifests(self) -> None:
        capabilities = load_thing_type_capabilities(repo_root=REPO_ROOT)

        self.assertEqual(capabilities["town"], ("sparkplug",))
        self.assertEqual(capabilities["raspi"], ("sparkplug",))
        self.assertEqual(capabilities["cloud"], ("sparkplug",))
        self.assertEqual(
            capabilities["unit"],
            ("sparkplug", "ble", "power", "board", "mcp", "video"),
        )
        self.assertEqual(capabilities["cloud-mcu"], ("sparkplug", "sqs", "power", "ecs"))
        self.assertEqual(capabilities["weather"], ("sparkplug", "ble", "power", "weather"))
        self.assertEqual(capabilities["power"], ("sparkplug", "ble", "power"))
        self.assertEqual(capabilities["power-si"], ("sparkplug", "thread", "power"))
        self.assertEqual(
            capabilities_for_thing_type("unit", repo_root=REPO_ROOT),
            ("sparkplug", "ble", "power", "board", "mcp", "video"),
        )
        self.assertEqual(
            capabilities_for_thing_type("cloud-mcu", repo_root=REPO_ROOT),
            ("sparkplug", "sqs", "power", "ecs"),
        )
        self.assertEqual(
            capabilities_for_thing_type("weather", repo_root=REPO_ROOT),
            ("sparkplug", "ble", "power", "weather"),
        )
        self.assertEqual(
            capabilities_for_thing_type("power-si", repo_root=REPO_ROOT),
            ("sparkplug", "thread", "power"),
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
compatible_rig_types = ["sensor-rig"]

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
        self.assertEqual(manifest.compatible_rig_types, ("sensor-rig",))
        self.assertEqual(manifest.shadow_contract("sensor-data").name, "sensor-data")


if __name__ == "__main__":
    unittest.main()
