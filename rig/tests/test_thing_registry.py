from __future__ import annotations

import unittest

from rig.thing_registry import (
    AwsThingRegistryClient,
    DeviceRegistration,
    ThingGroupNotFoundError,
)


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeIotClient:
    def __init__(self) -> None:
        self.describe_group_requests: list[str] = []
        self.list_group_requests: list[dict[str, object]] = []
        self.describe_requests: list[str] = []
        self.update_requests: list[dict[str, object]] = []
        self.missing_groups: set[str] = set()
        self._things: dict[str, dict[str, object]] = {
            "unit-bbbbbb": {
                "thingName": "unit-bbbbbb",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "rig-rig001",
                    "deviceType": "unit",
                    "name": "bot",
                    "shortId": "bbbbbb",
                    "capabilities": "sparkplug,mcu,board,mcp,video",
                },
                "version": 3,
            },
            "unit-aaaaaa": {
                "thingName": "unit-aaaaaa",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "rig-rig001",
                    "deviceType": "unit",
                    "name": "bot",
                    "shortId": "aaaaaa",
                    "capabilities": "sparkplug,mcu,board,mcp,video",
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
                    "capabilities": "sparkplug,mcu,board,mcp,video",
                },
                "version": 1,
            },
            "unit-other": {
                "thingName": "unit-other",
                "thingTypeName": "unit",
                "attributes": {
                    "townId": "town-berlin",
                    "rigId": "rig-other",
                    "deviceType": "unit",
                    "name": "bot",
                    "shortId": "other01",
                    "capabilities": "sparkplug,mcu,board,mcp,video",
                },
                "version": 2,
            },
            "rig-rig001": {
                "thingName": "rig-rig001",
                "thingTypeName": "rig",
                "attributes": {
                    "name": "rig-a",
                    "shortId": "rig001",
                    "townId": "town-berlin",
                    "rigType": "raspi",
                    "capabilities": "sparkplug",
                },
                "version": 4,
            },
        }

    def describe_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
        self.describe_group_requests.append(thingGroupName)
        if thingGroupName in self.missing_groups:
            raise FakeClientError("ResourceNotFoundException")
        return {"thingGroupName": thingGroupName}

    def list_things_in_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.list_group_requests.append(kwargs)
        group_name = kwargs["thingGroupName"]
        assert isinstance(group_name, str)
        if group_name == "town-berlin":
            return {"things": ["rig-rig001", "unit-other"]}
        if "nextToken" not in kwargs:
            return {
                "things": ["unit-bbbbbb", "unit-aaaaaa"],
                "nextToken": "page-2",
            }
        return {
            "things": ["unit-aaaaaa", "rig-only", "unit-other"]
        }

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


class ThingRegistryTests(unittest.TestCase):
    def test_list_rig_things_uses_thing_group_membership_and_describe_thing(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        registrations = registry.list_rig_things("rig-rig001")

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
                    rig_name="rig-rig001",
                    town_id="town-berlin",
                    rig_id="rig-rig001",
                    version=5,
                ),
                DeviceRegistration(
                    thing_name="unit-bbbbbb",
                    thing_type="unit",
                    name="bot",
                    short_id="bbbbbb",
                    capabilities_set=("sparkplug", "mcu", "board", "mcp", "video"),
                    town_name="town-berlin",
                    rig_name="rig-rig001",
                    town_id="town-berlin",
                    rig_id="rig-rig001",
                    version=3,
                ),
            ],
        )
        self.assertEqual(client.describe_group_requests, ["rig-rig001"])
        self.assertEqual(
            client.list_group_requests,
            [
                {"thingGroupName": "rig-rig001", "maxResults": 100},
                {
                    "thingGroupName": "rig-rig001",
                    "maxResults": 100,
                    "nextToken": "page-2",
                },
            ],
        )
        self.assertEqual(
            client.describe_requests,
            ["rig-only", "unit-aaaaaa", "unit-bbbbbb", "unit-other"],
        )

    def test_list_rig_things_raises_when_dynamic_group_is_missing(self) -> None:
        client = FakeIotClient()
        client.missing_groups.add("rig-missing")
        registry = AwsThingRegistryClient(client)

        with self.assertRaises(ThingGroupNotFoundError):
            registry.list_rig_things("rig-missing")

    def test_describe_thing_requires_rig_id_attribute(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        with self.assertRaisesRegex(RuntimeError, "missing required IoT registry attribute 'rigId'"):
            registry.describe_thing("rig-only")

    def test_describe_rig_returns_matching_rig_thing(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        registration = registry.describe_rig("rig-rig001")

        self.assertEqual(registration.thing_name, "rig-rig001")
        self.assertEqual(registration.thing_type, "rig")
        self.assertEqual(registration.name, "rig-a")
        self.assertEqual(registration.short_id, "rig001")
        self.assertEqual(registration.town_name, "town-berlin")
        self.assertEqual(registration.rig_name, "rig-a")
        self.assertEqual(registration.town_id, "town-berlin")
        self.assertEqual(registration.rig_id, "rig-rig001")
        self.assertEqual(registration.capabilities_set, ("sparkplug",))


if __name__ == "__main__":
    unittest.main()
