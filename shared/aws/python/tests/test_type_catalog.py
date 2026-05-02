from __future__ import annotations

import json
from pathlib import Path
import unittest

from aws.type_catalog import (
    TYPE_CATALOG_ROOT,
    build_type_records,
    device_type_path,
    normalize_catalog_path,
    rig_type_path,
    town_type_path,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


class TypeCatalogTests(unittest.TestCase):
    def test_hardcoded_paths_are_stable(self) -> None:
        self.assertEqual(TYPE_CATALOG_ROOT, "/txing")
        self.assertEqual(town_type_path(), "/txing/town")
        self.assertEqual(rig_type_path("raspi"), "/txing/town/raspi")
        self.assertEqual(device_type_path("cloud", "time"), "/txing/town/cloud/time")
        self.assertEqual(normalize_catalog_path("ssm:/txing/town/cloud"), "/txing/town/cloud")
        self.assertEqual(normalize_catalog_path("town/raspi/unit"), "/txing/town/raspi/unit")

    def test_expected_records_contain_only_type_catalog_and_compatibility(self) -> None:
        records = build_type_records(repo_root=REPO_ROOT)

        self.assertEqual(
            set(records),
            {
                "/txing/town",
                "/txing/town/raspi",
                "/txing/town/raspi/unit",
                "/txing/town/cloud",
                "/txing/town/cloud/time",
            },
        )
        self.assertEqual(records["/txing/town/raspi"]["defaultName"], "server")
        self.assertEqual(records["/txing/town/cloud"]["defaultName"], "aws")
        self.assertEqual(records["/txing/town/raspi/unit"]["defaultName"], "bot")
        self.assertEqual(records["/txing/town/cloud/time"]["defaultName"], "clock")
        self.assertEqual(records["/txing/town/raspi/unit"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/cloud/time"]["rigType"], "cloud")

    def test_records_are_json_serializable(self) -> None:
        records = build_type_records(repo_root=REPO_ROOT)
        payload = json.dumps(records, sort_keys=True)

        self.assertIn("/txing/town/cloud/time", payload)
        self.assertNotIn("capabilitiesSet", payload)


if __name__ == "__main__":
    unittest.main()
