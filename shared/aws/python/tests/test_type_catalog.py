from __future__ import annotations

import json
from pathlib import Path
import unittest

from aws.type_catalog import (
    SsmTypeCatalog,
    TYPE_CATALOG_ROOT,
    TypeCatalogError,
    build_type_records,
    device_type_path,
    normalize_catalog_path,
    rig_type_path,
    town_type_path,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_json_object_or_array_value(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


class _FakeSsmClient:
    def __init__(self) -> None:
        self.parameters: dict[str, str] = {}
        self.put_requests: list[dict[str, object]] = []
        self.delete_requests: list[list[str]] = []

    def get_parameters_by_path(self, **kwargs: object) -> dict[str, object]:
        path = str(kwargs["Path"]).rstrip("/")
        prefix = f"{path}/"
        return {
            "Parameters": [
                {"Name": name, "Value": self.parameters[name]}
                for name in sorted(self.parameters)
                if name.startswith(prefix)
            ]
        }

    def put_parameter(self, **kwargs: object) -> None:
        self.put_requests.append(kwargs)
        self.parameters[str(kwargs["Name"])] = str(kwargs["Value"])

    def delete_parameters(self, *, Names: list[str]) -> dict[str, object]:
        self.delete_requests.append(list(Names))
        for name in Names:
            self.parameters.pop(name, None)
        return {"DeletedParameters": Names, "InvalidParameters": []}


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
        self.assertEqual(records["/txing/town/raspi"]["thingType"], "raspi")
        self.assertEqual(records["/txing/town/cloud"]["thingType"], "cloud")
        self.assertEqual(records["/txing/town/raspi"]["requiredAttributes"], ["name", "shortId", "townId"])
        self.assertEqual(records["/txing/town/cloud/time"]["requiredAttributes"], ["name", "shortId", "townId", "rigId"])
        self.assertEqual(records["/txing/town/raspi/unit"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/cloud/time"]["rigType"], "cloud")

    def test_records_are_json_serializable(self) -> None:
        records = build_type_records(repo_root=REPO_ROOT)
        payload = json.dumps(records, sort_keys=True)

        self.assertIn("/txing/town/cloud/time", payload)
        self.assertNotIn("capabilitiesSet", payload)

    def test_sync_writes_leaf_parameters_and_deletes_stale_catalog_values(self) -> None:
        ssm = _FakeSsmClient()
        ssm.parameters.update(
            {
                "/txing/town": '{"kind":"townType"}',
                "/txing/town/cloud/time": '{"kind":"deviceType"}',
                "/txing/town/stale/kind": "rigType",
            }
        )
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)

        catalog.sync()

        self.assertNotIn("/txing/town", ssm.parameters)
        self.assertNotIn("/txing/town/cloud/time", ssm.parameters)
        self.assertNotIn("/txing/town/stale/kind", ssm.parameters)
        self.assertEqual(ssm.parameters["/txing/town/kind"], "townType")
        self.assertEqual(ssm.parameters["/txing/town/raspi/kind"], "rigType")
        self.assertEqual(ssm.parameters["/txing/town/raspi/unit/kind"], "deviceType")
        self.assertEqual(ssm.parameters["/txing/town/cloud/kind"], "rigType")
        self.assertEqual(ssm.parameters["/txing/town/cloud/time/kind"], "deviceType")
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/time/capabilities"],
            "sparkplug,mcp,time",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/time/shadows/time/schema"],
            "aws/time-shadow.schema.json",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/time/web/adapter"],
            "web/time-adapter.tsx",
        )
        self.assertFalse(
            any(
                _is_json_object_or_array_value(str(request["Value"]))
                for request in ssm.put_requests
            )
        )

    def test_get_record_reconstructs_dict_without_absorbing_child_type_records(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()

        town_record = catalog.get_record("/txing/town")
        cloud_record = catalog.get_record("/txing/town/cloud")
        time_record = catalog.get_record("/txing/town/cloud/time")

        self.assertNotIn("cloud", town_record)
        self.assertNotIn("time", cloud_record)
        self.assertEqual(cloud_record["hostServices"], [])
        self.assertEqual(time_record["capabilities"], ["sparkplug", "mcp", "time"])
        self.assertEqual(
            time_record["shadows"]["time"],
            {
                "schema": "aws/time-shadow.schema.json",
                "default": "aws/default-time-shadow.json",
            },
        )

    def test_list_records_groups_leaf_parameters_by_kind_marker(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()

        self.assertEqual(
            [path for path, _record in catalog.list_records("/txing/town/cloud")],
            ["/txing/town/cloud", "/txing/town/cloud/time"],
        )

    def test_required_list_leaf_must_not_be_empty(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()
        ssm.parameters["/txing/town/cloud/time/capabilities"] = ""

        with self.assertRaisesRegex(TypeCatalogError, "capabilities"):
            catalog.get_record("/txing/town/cloud/time")

    def test_list_leaf_items_must_not_contain_commas(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        record = build_type_records(repo_root=REPO_ROOT)["/txing/town/cloud/time"]
        record = {**record, "capabilities": ["sparkplug", "bad,value"]}

        with self.assertRaisesRegex(TypeCatalogError, "must not contain"):
            catalog.put_record("/txing/town/cloud/time", record)


if __name__ == "__main__":
    unittest.main()
