from __future__ import annotations

import unittest

from aws.type_catalog import SsmTypeCatalog, build_type_records
from rig.thing_registry import (
    AwsThingRegistryClient,
    DeviceRegistration,
)


class FakeIotClient:
    def __init__(self) -> None:
        self.search_requests: list[dict[str, object]] = []
        self.describe_requests: list[str] = []
        self.update_requests: list[dict[str, object]] = []
        self._things: dict[str, dict[str, object]] = {
            "unit-bbbbbb": {
                "thingName": "unit-bbbbbb",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "raspi-rig001",
                    "name": "bot",
                    "shortId": "bbbbbb",
                },
                "version": 3,
            },
            "unit-aaaaaa": {
                "thingName": "unit-aaaaaa",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "raspi-rig001",
                    "name": "bot",
                    "shortId": "aaaaaa",
                },
                "version": 5,
            },
            "rig-only": {
                "thingName": "rig-only",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "name": "bot",
                    "shortId": "rigonly",
                },
                "version": 1,
            },
            "unit-other": {
                "thingName": "unit-other",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "rig-other",
                    "name": "bot",
                    "shortId": "other01",
                },
                "version": 2,
            },
            "raspi-rig001": {
                "thingName": "raspi-rig001",
                "thingTypeName": "raspi",
                "attributes": {
                    "name": "rig-a",
                    "shortId": "rig001",
                    "townId": "town-berlin",
                },
                "version": 4,
            },
        }

    def search_index(self, **kwargs: object) -> dict[str, object]:
        self.search_requests.append(kwargs)
        query = str(kwargs["queryString"])
        if query == "attributes.rigId:raspi-rig001 AND attributes.townId:*":
            return {
                "things": [
                    {"thingName": "unit-bbbbbb"},
                    {"thingName": "unit-aaaaaa"},
                    {"thingName": "rig-only"},
                ]
            }
        return {"things": []}

    def describe_thing(self, *, thingName: str) -> dict[str, object]:
        self.describe_requests.append(thingName)
        return dict(self._things[thingName])

    def update_thing(self, **kwargs: object) -> None:
        self.update_requests.append(kwargs)
        thing_name = kwargs["thingName"]
        assert isinstance(thing_name, str)
        payload = kwargs["attributePayload"]
        assert isinstance(payload, dict)
        attributes = payload["attributes"]
        assert isinstance(attributes, dict)
        current = self._things[thing_name]
        merged = dict(current["attributes"])
        merged.update(attributes)
        current["attributes"] = merged
        current["version"] = int(current["version"]) + 1


class FakeSsmClient:
    def __init__(self) -> None:
        self.parameters: dict[str, str] = {}
        catalog = SsmTypeCatalog(self)
        for path, record in build_type_records().items():
            catalog.put_record(path, record)

    def get_parameters_by_path(self, **kwargs: object) -> dict[str, object]:
        path = str(kwargs["Path"]).rstrip("/")
        prefix = f"{path}/"
        return {
            "Parameters": [
                {"Name": name, "Value": value}
                for name, value in sorted(self.parameters.items())
                if name.startswith(prefix)
            ]
        }

    def put_parameter(self, **kwargs: object) -> None:
        self.parameters[str(kwargs["Name"])] = str(kwargs["Value"])

    def delete_parameters(self, *, Names: list[str]) -> dict[str, object]:
        for name in Names:
            self.parameters.pop(name, None)
        return {"DeletedParameters": Names, "InvalidParameters": []}


def make_registry(client: FakeIotClient) -> AwsThingRegistryClient:
    return AwsThingRegistryClient(client, type_catalog=SsmTypeCatalog(FakeSsmClient()))


class ThingRegistryTests(unittest.TestCase):
    def test_list_rig_things_uses_fleet_index_and_describe_thing(self) -> None:
        client = FakeIotClient()
        registry = make_registry(client)

        registrations = registry.list_rig_things("raspi-rig001")

        self.assertEqual(
            registrations,
            [
                DeviceRegistration(
                    thing_name="unit-aaaaaa",
                    thing_type="unit",
                    name="bot",
                    short_id="aaaaaa",
                    capabilities_set=("sparkplug", "mcu", "board", "mcp", "video"),
                    town_name="town-berlin",
                    rig_name="raspi-rig001",
                    town_id="town-berlin",
                    rig_id="raspi-rig001",
                    version=5,
                ),
                DeviceRegistration(
                    thing_name="unit-bbbbbb",
                    thing_type="unit",
                    name="bot",
                    short_id="bbbbbb",
                    capabilities_set=("sparkplug", "mcu", "board", "mcp", "video"),
                    town_name="town-berlin",
                    rig_name="raspi-rig001",
                    town_id="town-berlin",
                    rig_id="raspi-rig001",
                    version=3,
                ),
            ],
        )
        self.assertEqual(
            client.search_requests,
            [
                {
                    "indexName": "AWS_Things",
                    "queryString": "attributes.rigId:raspi-rig001 AND attributes.townId:*",
                    "maxResults": 100,
                },
            ],
        )
        self.assertEqual(
            client.describe_requests,
            ["rig-only", "unit-aaaaaa", "raspi-rig001", "unit-bbbbbb", "raspi-rig001"],
        )

    def test_describe_thing_requires_rig_id_attribute(self) -> None:
        client = FakeIotClient()
        registry = make_registry(client)

        with self.assertRaisesRegex(RuntimeError, "missing required IoT registry attribute 'rigId'"):
            registry.describe_thing("rig-only")

    def test_describe_rig_returns_matching_rig_thing(self) -> None:
        client = FakeIotClient()
        registry = make_registry(client)

        registration = registry.describe_rig("raspi-rig001")

        self.assertEqual(registration.thing_name, "raspi-rig001")
        self.assertEqual(registration.thing_type, "raspi")
        self.assertEqual(registration.name, "rig-a")
        self.assertEqual(registration.short_id, "rig001")
        self.assertEqual(registration.town_name, "town-berlin")
        self.assertEqual(registration.rig_name, "rig-a")
        self.assertEqual(registration.town_id, "town-berlin")
        self.assertEqual(registration.rig_id, "raspi-rig001")
        self.assertEqual(registration.capabilities_set, ("sparkplug",))


if __name__ == "__main__":
    unittest.main()
