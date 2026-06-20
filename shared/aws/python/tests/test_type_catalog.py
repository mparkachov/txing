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
        self.assertEqual(device_type_path("cloud", "cloud-mcu"), "/txing/town/cloud/cloud-mcu")
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
                "/txing/town/raspi/weather",
                "/txing/town/raspi/power",
                "/txing/town/raspi/power-si",
                "/txing/town/cloud",
                "/txing/town/cloud/cloud-mcu",
            },
        )
        self.assertEqual(records["/txing/town/raspi"]["defaultName"], "server")
        self.assertEqual(records["/txing/town/cloud"]["defaultName"], "aws")
        self.assertEqual(records["/txing/town/raspi/unit"]["defaultName"], "bot")
        self.assertEqual(records["/txing/town/raspi/weather"]["defaultName"], "outside")
        self.assertEqual(records["/txing/town/raspi/power"]["defaultName"], "power")
        self.assertEqual(records["/txing/town/raspi/power-si"]["defaultName"], "power-si")
        self.assertEqual(records["/txing/town/cloud/cloud-mcu"]["defaultName"], "cloud")
        self.assertEqual(records["/txing/town/raspi"]["thingType"], "raspi")
        self.assertEqual(records["/txing/town/cloud"]["thingType"], "cloud")
        self.assertEqual(records["/txing/town/raspi"]["requiredAttributes"], ["name", "shortId", "townId"])
        self.assertEqual(
            records["/txing/town/cloud/cloud-mcu"]["requiredAttributes"],
            ["name", "shortId", "townId", "rigId"],
        )
        self.assertEqual(records["/txing/town/raspi/unit"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/raspi/weather"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/raspi/power"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/raspi/power-si"]["rigType"], "raspi")
        self.assertEqual(records["/txing/town/cloud/cloud-mcu"]["rigType"], "cloud")
        self.assertEqual(records["/txing/town/raspi"]["redconCommandLevels"], ["1", "4"])
        self.assertEqual(records["/txing/town/cloud"]["redconCommandLevels"], ["1", "4"])
        self.assertEqual(records["/txing/town/raspi/unit"]["redconCommandLevels"], ["4", "3", "2", "1"])
        self.assertEqual(records["/txing/town/raspi/weather"]["redconCommandLevels"], ["4"])
        self.assertEqual(records["/txing/town/raspi/power"]["redconCommandLevels"], ["4", "3"])
        self.assertEqual(records["/txing/town/raspi/power-si"]["redconCommandLevels"], ["4", "3"])
        self.assertEqual(records["/txing/town/cloud/cloud-mcu"]["redconCommandLevels"], ["4", "3"])
        self.assertEqual(
            records["/txing/town/raspi/unit"]["redconRules"],
            {
                "1": ["sparkplug", "ble", "power", "board", "mcp", "video"],
                "2": ["sparkplug", "ble", "power", "board", "mcp"],
                "3": ["sparkplug", "ble", "power"],
                "4": ["sparkplug", "ble"],
            },
        )
        self.assertEqual(
            records["/txing/town/raspi/power"]["redconRules"],
            {
                "3": ["sparkplug", "ble", "power"],
                "4": ["sparkplug", "ble"],
            },
        )
        self.assertEqual(
            records["/txing/town/raspi/power-si"]["redconRules"],
            {
                "3": ["sparkplug", "thread", "power"],
                "4": ["sparkplug", "thread"],
            },
        )
        self.assertEqual(
            records["/txing/town/cloud/cloud-mcu"]["redconRules"],
            {
                "3": ["sparkplug", "sqs", "power"],
                "4": ["sparkplug", "sqs"],
            },
        )

    def test_records_are_json_serializable(self) -> None:
        records = build_type_records(repo_root=REPO_ROOT)
        payload = json.dumps(records, sort_keys=True)

        self.assertIn("/txing/town/cloud/cloud-mcu", payload)
        self.assertNotIn("capabilitiesSet", payload)

    def test_sync_writes_leaf_parameters_and_deletes_stale_catalog_values(self) -> None:
        ssm = _FakeSsmClient()
        ssm.parameters.update(
            {
                "/txing/town": '{"kind":"townType"}',
                "/txing/town/cloud/cloud-mcu": '{"kind":"deviceType"}',
                "/txing/town/stale/kind": "rigType",
            }
        )
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)

        catalog.sync()

        self.assertNotIn("/txing/town", ssm.parameters)
        self.assertNotIn("/txing/town/cloud/cloud-mcu", ssm.parameters)
        self.assertNotIn("/txing/town/stale/kind", ssm.parameters)
        self.assertEqual(ssm.parameters["/txing/town/kind"], "townType")
        self.assertEqual(ssm.parameters["/txing/town/raspi/kind"], "rigType")
        self.assertEqual(ssm.parameters["/txing/town/raspi/unit/kind"], "deviceType")
        self.assertEqual(ssm.parameters["/txing/town/cloud/kind"], "rigType")
        self.assertEqual(ssm.parameters["/txing/town/cloud/cloud-mcu/kind"], "deviceType")
        self.assertEqual(ssm.parameters["/txing/town/raspi/redconCommandLevels"], "1,4")
        self.assertEqual(ssm.parameters["/txing/town/cloud/redconCommandLevels"], "1,4")
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/cloud-mcu/capabilities"],
            "sparkplug,sqs,power,ecs",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/capabilities"],
            "sparkplug,ble,power,board,mcp,video",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/redconCommandLevels"],
            "4,3,2,1",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/redconRules/1"],
            "sparkplug,ble,power,board,mcp,video",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/redconRules/2"],
            "sparkplug,ble,power,board,mcp",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/redconRules/3"],
            "sparkplug,ble,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/unit/redconRules/4"],
            "sparkplug,ble",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/weather/capabilities"],
            "sparkplug,ble,power,weather",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power/capabilities"],
            "sparkplug,ble,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/capabilities"],
            "sparkplug,thread,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/weather/redconCommandLevels"],
            "4",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power/redconCommandLevels"],
            "4,3",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/redconCommandLevels"],
            "4,3",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power/redconRules/3"],
            "sparkplug,ble,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/redconRules/3"],
            "sparkplug,thread,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/redconRules/4"],
            "sparkplug,thread",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/shadows/thread/schema"],
            "aws/thread-shadow.schema.json",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/raspi/power-si/web/adapter"],
            "web/power-si-adapter.tsx",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/cloud-mcu/redconRules/3"],
            "sparkplug,sqs,power",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/cloud-mcu/redconRules/4"],
            "sparkplug,sqs",
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/cloud-mcu/shadows/power/schema"],
            "aws/power-shadow.schema.json",
        )
        self.assertIn(
            '"desiredRedcon"',
            ssm.parameters["/txing/town/cloud/cloud-mcu/shadows/power/defaultPayload"],
        )
        self.assertEqual(
            ssm.parameters["/txing/town/cloud/cloud-mcu/web/adapter"],
            "web/cloud-mcu-adapter.tsx",
        )
        self.assertFalse(
            any(
                _is_json_object_or_array_value(str(request["Value"]))
                for request in ssm.put_requests
                if not str(request["Name"]).endswith("/defaultPayload")
            )
        )

    def test_get_record_reconstructs_dict_without_absorbing_child_type_records(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()

        town_record = catalog.get_record("/txing/town")
        cloud_record = catalog.get_record("/txing/town/cloud")
        cloud_mcu_record = catalog.get_record("/txing/town/cloud/cloud-mcu")

        self.assertNotIn("cloud", town_record)
        self.assertNotIn("cloud-mcu", cloud_record)
        self.assertEqual(cloud_record["hostServices"], [])
        self.assertEqual(cloud_record["redconCommandLevels"], ["1", "4"])
        self.assertEqual(cloud_mcu_record["capabilities"], ["sparkplug", "sqs", "power", "ecs"])
        self.assertEqual(cloud_mcu_record["redconCommandLevels"], ["4", "3"])
        self.assertEqual(
            cloud_mcu_record["redconRules"],
            {"3": ["sparkplug", "sqs", "power"], "4": ["sparkplug", "sqs"]},
        )
        self.assertEqual(
            cloud_mcu_record["shadows"]["power"]["schema"],
            "aws/power-shadow.schema.json",
        )
        self.assertEqual(
            cloud_mcu_record["shadows"]["power"]["default"],
            "aws/default-power-shadow.json",
        )
        self.assertIn('"desiredRedcon"', cloud_mcu_record["shadows"]["power"]["defaultPayload"])

    def test_list_records_groups_leaf_parameters_by_kind_marker(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()

        self.assertEqual(
            [path for path, _record in catalog.list_records("/txing/town/cloud")],
            ["/txing/town/cloud", "/txing/town/cloud/cloud-mcu"],
        )
        self.assertEqual(
            [path for path, _record in catalog.list_records("/txing/town/raspi")],
            [
                "/txing/town/raspi",
                "/txing/town/raspi/power",
                "/txing/town/raspi/power-si",
                "/txing/town/raspi/unit",
                "/txing/town/raspi/weather",
            ],
        )

    def test_required_list_leaf_must_not_be_empty(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        catalog.sync()
        ssm.parameters["/txing/town/cloud/cloud-mcu/capabilities"] = ""

        with self.assertRaisesRegex(TypeCatalogError, "capabilities"):
            catalog.get_record("/txing/town/cloud/cloud-mcu")

    def test_list_leaf_items_must_not_contain_commas(self) -> None:
        ssm = _FakeSsmClient()
        catalog = SsmTypeCatalog(ssm, repo_root=REPO_ROOT)
        record = build_type_records(repo_root=REPO_ROOT)["/txing/town/cloud/cloud-mcu"]
        record = {**record, "capabilities": ["sparkplug", "bad,value"]}

        with self.assertRaisesRegex(TypeCatalogError, "must not contain"):
            catalog.put_record("/txing/town/cloud/cloud-mcu", record)


if __name__ == "__main__":
    unittest.main()
