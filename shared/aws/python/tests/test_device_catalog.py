from __future__ import annotations

from pathlib import Path
import unittest

from aws.device_catalog import (
    DeviceTypeNotFoundError,
    discover_repo_root,
    list_loadable_device_types,
    load_device_manifest,
)


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
            manifest.shadow_schema,
            REPO_ROOT / "devices" / "unit" / "aws" / "shadow.schema.json",
        )
        self.assertEqual(
            manifest.default_shadow,
            REPO_ROOT / "devices" / "unit" / "aws" / "default-shadow.json",
        )
        self.assertEqual(
            manifest.render_board_video_channel_name(device_id="unit-a7k2p9"),
            "unit-a7k2p9-board-video",
        )

    def test_template_is_not_loadable(self) -> None:
        with self.assertRaises(DeviceTypeNotFoundError):
            load_device_manifest("template", repo_root=REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
