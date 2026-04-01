from __future__ import annotations

import unittest

from rig.thing_registry import AwsThingRegistryClient, ThingRegistration


class FakeIotClient:
    def __init__(self) -> None:
        self.search_requests: list[dict[str, object]] = []
        self.describe_requests: list[str] = []
        self.update_requests: list[dict[str, object]] = []
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
        }

    def search_index(self, **kwargs: object) -> dict[str, object]:
        self.search_requests.append(kwargs)
        if "nextToken" not in kwargs:
            return {
                "things": [
                    {"thingName": "txing-b"},
                    {"thingName": "txing-a"},
                ],
                "nextToken": "page-2",
            }
        return {
            "things": [
                {"thingName": "txing-a"},
            ]
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
    def test_list_rig_things_uses_fleet_index_and_describe_thing(self) -> None:
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
        self.assertEqual(client.search_requests[0]["queryString"], "attributes.rig:rig-a")
        self.assertEqual(client.describe_requests, ["txing-a", "txing-b"])

    def test_describe_thing_requires_rig_attribute(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        with self.assertRaisesRegex(RuntimeError, "missing required IoT registry attribute 'rig'"):
            registry.describe_thing("rig-only")

    def test_update_registration_merges_rig_and_ble_device_id(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        registration = registry.update_registration(
            "txing-a",
            rig_name="rig-z",
            ble_device_id="CC:CC:CC:CC:CC:CC",
            expected_version=5,
        )

        self.assertEqual(
            client.update_requests[0],
            {
                "thingName": "txing-a",
                "attributePayload": {
                    "attributes": {
                        "rig": "rig-z",
                        "bleDeviceId": "CC:CC:CC:CC:CC:CC",
                    },
                    "merge": True,
                },
                "expectedVersion": 5,
            },
        )
        self.assertEqual(registration.rig_name, "rig-z")
        self.assertEqual(registration.ble_device_id, "CC:CC:CC:CC:CC:CC")
        self.assertEqual(registration.version, 6)

    def test_update_registration_can_refresh_rig_without_touching_ble_device_id(self) -> None:
        client = FakeIotClient()
        registry = AwsThingRegistryClient(client)

        registration = registry.update_registration(
            "txing-b",
            rig_name="rig-a",
            ble_device_id=None,
        )

        self.assertEqual(
            client.update_requests[0]["attributePayload"],
            {
                "attributes": {
                    "rig": "rig-a",
                },
                "merge": True,
            },
        )
        self.assertEqual(registration.ble_device_id, "BB:BB:BB:BB:BB:BB")


if __name__ == "__main__":
    unittest.main()
