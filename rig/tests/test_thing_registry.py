from __future__ import annotations

import unittest

from rig.thing_registry import (
    AwsThingRegistryClient,
    ThingGroupNotFoundError,
    ThingRegistration,
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
            "txing-b": {
                "thingName": "txing-b",
                "attributes": {"rig": "rig-a", "bleDeviceId": "BB:BB:BB:BB:BB:BB"},
                "version": 3,
            },
            "txing-a": {
                "thingName": "txing-a",
                "attributes": {"rig": "rig-a", "bleDeviceId": "AA:AA:AA:AA:AA:AA"},
                "version": 5,
            },
            "rig-only": {
                "thingName": "rig-only",
                "attributes": {"bleDeviceId": "missing-rig"},
                "version": 1,
            },
            "txing-other": {
                "thingName": "txing-other",
                "attributes": {"rig": "rig-b", "bleDeviceId": "DD:DD:DD:DD:DD:DD"},
                "version": 2,
            },
        }

    def describe_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
        self.describe_group_requests.append(thingGroupName)
        if thingGroupName in self.missing_groups:
            raise FakeClientError("ResourceNotFoundException")
        return {"thingGroupName": thingGroupName}

    def list_things_in_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.list_group_requests.append(kwargs)
        if "nextToken" not in kwargs:
            return {
                "things": ["txing-b", "txing-a"],
                "nextToken": "page-2",
            }
        return {
            "things": ["txing-a", "rig-only", "txing-other"]
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

        registrations = registry.list_rig_things("rig-a")

        self.assertEqual(
            registrations,
            [
                ThingRegistration(
                    thing_name="txing-a",
                    rig_name="rig-a",
                    ble_device_id="AA:AA:AA:AA:AA:AA",
                    version=5,
                ),
                ThingRegistration(
                    thing_name="txing-b",
                    rig_name="rig-a",
                    ble_device_id="BB:BB:BB:BB:BB:BB",
                    version=3,
                ),
            ],
        )
        self.assertEqual(client.describe_group_requests, ["rig-a"])
        self.assertEqual(
            client.list_group_requests,
            [
                {"thingGroupName": "rig-a", "maxResults": 100},
                {
                    "thingGroupName": "rig-a",
                    "maxResults": 100,
                    "nextToken": "page-2",
                },
            ],
        )
        self.assertEqual(
            client.describe_requests,
            ["rig-only", "txing-a", "txing-b", "txing-other"],
        )

    def test_list_rig_things_raises_when_dynamic_group_is_missing(self) -> None:
        client = FakeIotClient()
        client.missing_groups.add("rig-missing")
        registry = AwsThingRegistryClient(client)

        with self.assertRaises(ThingGroupNotFoundError):
            registry.list_rig_things("rig-missing")

    def test_describe_thing_requires_rig_attribute(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        with self.assertRaisesRegex(RuntimeError, "missing required IoT registry attribute 'rig'"):
            registry.describe_thing("rig-only")

    def test_update_ble_device_id_only_merges_ble_device_id(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        registration = registry.update_ble_device_id(
            "txing-a",
            ble_device_id="CC:CC:CC:CC:CC:CC",
            expected_version=5,
        )

        self.assertEqual(
            client.update_requests[0],
            {
                "thingName": "txing-a",
                "attributePayload": {
                    "attributes": {
                        "bleDeviceId": "CC:CC:CC:CC:CC:CC",
                    },
                    "merge": True,
                },
                "expectedVersion": 5,
            },
        )
        self.assertEqual(registration.rig_name, "rig-a")
        self.assertEqual(registration.ble_device_id, "CC:CC:CC:CC:CC:CC")
        self.assertEqual(registration.version, 6)


if __name__ == "__main__":
    unittest.main()
