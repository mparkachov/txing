from __future__ import annotations

import json
from pathlib import Path
import unittest

from aws.device_catalog import DeviceTypeNotFoundError
from aws.device_registry import AwsDeviceRegistry


REPO_ROOT = Path(__file__).resolve().parents[4]


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _SequenceRandom:
    def __init__(self, sequence: str) -> None:
        self._values = list(sequence)

    def choice(self, alphabet: str) -> str:
        if not self._values:
            raise AssertionError("choice() exhausted")
        value = self._values.pop(0)
        if value not in alphabet:
            raise AssertionError(f"{value!r} is not in {alphabet!r}")
        return value


class _FakeIotClient:
    def __init__(self) -> None:
        self.create_thing_requests: list[dict[str, object]] = []
        self.update_thing_requests: list[dict[str, object]] = []
        self.describe_thing_type_requests: list[str] = []
        self.create_thing_type_requests: list[dict[str, object]] = []
        self.describe_group_requests: list[str] = []
        self.create_group_requests: list[dict[str, object]] = []
        self.update_group_requests: list[dict[str, object]] = []
        self.search_index_requests: list[dict[str, object]] = []
        self.list_things_requests: list[dict[str, object]] = []
        self.search_visible_thing_names: set[str] | None = None
        self.groups: set[str] = set()
        self.thing_types: dict[str, dict[str, object]] = {}
        self._things: dict[str, dict[str, object]] = {
            "town-ber001": {
                "thingName": "town-ber001",
                "thingTypeName": "town",
                "attributes": {
                    "name": "berlin",
                    "shortId": "ber001",
                    "capabilitiesSet": "sparkplug",
                },
                "version": 1,
            },
            "rig-rig001": {
                "thingName": "rig-rig001",
                "thingTypeName": "rig",
                "attributes": {
                    "name": "rig-a",
                    "shortId": "rig001",
                    "town": "berlin",
                    "capabilitiesSet": "sparkplug",
                },
                "version": 1,
            },
            "unit-aaaaaa": {
                "thingName": "unit-aaaaaa",
                "thingTypeName": "unit",
                "attributes": {
                    "town": "berlin",
                    "rig": "rig-a",
                    "name": "bot",
                    "shortId": "aaaaaa",
                    "capabilitiesSet": "sparkplug,mcu,board,mcp,video",
                },
                "version": 1,
            },
            "unit-z9x8w7": {
                "thingName": "unit-z9x8w7",
                "thingTypeName": "unit",
                "attributes": {
                    "town": "berlin",
                    "rig": "rig-a",
                    "name": "bot",
                    "shortId": "z9x8w7",
                    "capabilitiesSet": "sparkplug,mcu,board,mcp,video",
                },
                "version": 7,
            },
        }

    def describe_thing(self, *, thingName: str) -> dict[str, object]:
        try:
            return dict(self._things[thingName])
        except KeyError as err:
            raise _FakeClientError("ResourceNotFoundException") from err

    def create_thing(self, **kwargs: object) -> dict[str, object]:
        self.create_thing_requests.append(kwargs)
        thing_name = kwargs["thingName"]
        assert isinstance(thing_name, str)
        payload = kwargs["attributePayload"]
        assert isinstance(payload, dict)
        attributes = payload["attributes"]
        assert isinstance(attributes, dict)
        thing_type_name = kwargs["thingTypeName"]
        assert isinstance(thing_type_name, str)
        self._things[thing_name] = {
            "thingName": thing_name,
            "thingTypeName": thing_type_name,
            "attributes": dict(attributes),
            "version": 1,
        }
        return {"thingName": thing_name}

    def update_thing(self, **kwargs: object) -> dict[str, object]:
        self.update_thing_requests.append(kwargs)
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
        return {"thingName": thing_name}

    def describe_thing_type(self, *, thingTypeName: str) -> dict[str, object]:
        self.describe_thing_type_requests.append(thingTypeName)
        if thingTypeName not in self.thing_types:
            raise _FakeClientError("ResourceNotFoundException")
        return {
            "thingTypeName": thingTypeName,
            "thingTypeProperties": dict(self.thing_types[thingTypeName]),
        }

    def create_thing_type(self, **kwargs: object) -> dict[str, object]:
        self.create_thing_type_requests.append(kwargs)
        thing_type_name = kwargs["thingTypeName"]
        assert isinstance(thing_type_name, str)
        thing_type_properties = kwargs["thingTypeProperties"]
        assert isinstance(thing_type_properties, dict)
        self.thing_types[thing_type_name] = dict(thing_type_properties)
        return {"thingTypeName": thing_type_name}

    def describe_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
        self.describe_group_requests.append(thingGroupName)
        if thingGroupName not in self.groups:
            raise _FakeClientError("ResourceNotFoundException")
        return {"thingGroupName": thingGroupName}

    def create_dynamic_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.create_group_requests.append(kwargs)
        thing_group_name = kwargs["thingGroupName"]
        assert isinstance(thing_group_name, str)
        self.groups.add(thing_group_name)
        return {"thingGroupName": thing_group_name}

    def update_dynamic_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.update_group_requests.append(kwargs)
        return {"thingGroupName": kwargs["thingGroupName"]}

    def search_index(self, **kwargs: object) -> dict[str, object]:
        self.search_index_requests.append(kwargs)
        query_string = kwargs["queryString"]
        assert isinstance(query_string, str)
        matches: list[str] = []
        for thing_name, thing in self._things.items():
            attributes = thing["attributes"]
            assert isinstance(attributes, dict)
            thing_type_name = thing["thingTypeName"]
            assert isinstance(thing_type_name, str)
            if "thingTypeName:town" in query_string and thing_type_name != "town":
                continue
            if "thingTypeName:rig" in query_string and thing_type_name != "rig":
                continue
            if "attributes.name:berlin" in query_string and attributes.get("name") != "berlin":
                continue
            if "attributes.name:munich" in query_string and attributes.get("name") != "munich":
                continue
            if "attributes.name:rig-a" in query_string and attributes.get("name") != "rig-a":
                continue
            if "attributes.name:rig-b" in query_string and attributes.get("name") != "rig-b":
                continue
            if "attributes.town:berlin" in query_string and attributes.get("town") != "berlin":
                continue
            if "attributes.town:munich" in query_string and attributes.get("town") != "munich":
                continue
            matches.append(thing_name)
        if self.search_visible_thing_names is not None:
            matches = [
                thing_name
                for thing_name in matches
                if thing_name in self.search_visible_thing_names
            ]
        return {
            "things": [{"thingName": thing_name} for thing_name in sorted(matches)],
        }

    def list_things(self, **kwargs: object) -> dict[str, object]:
        self.list_things_requests.append(kwargs)
        return {
            "things": [
                {
                    "thingName": thing_name,
                }
                for thing_name in sorted(self._things)
            ]
        }


class _FakeIotDataClient:
    def __init__(self) -> None:
        self.shadows: dict[tuple[str, str | None], bytes] = {}
        self.get_requests: list[tuple[str, str | None]] = []
        self.update_requests: list[tuple[str, str | None, bytes]] = []

    def get_thing_shadow(self, *, thingName: str, shadowName: str | None = None) -> dict[str, object]:
        self.get_requests.append((thingName, shadowName))
        try:
            payload = self.shadows[(thingName, shadowName)]
        except KeyError as err:
            raise _FakeClientError("ResourceNotFoundException") from err
        return {"payload": payload}

    def update_thing_shadow(
        self,
        *,
        thingName: str,
        payload: bytes,
        shadowName: str | None = None,
    ) -> dict[str, object]:
        self.update_requests.append((thingName, shadowName, payload))
        self.shadows[(thingName, shadowName)] = payload
        return {"payload": payload}


class _FakeKinesisVideoClient:
    def __init__(self) -> None:
        self.channels: set[str] = set()
        self.describe_requests: list[str] = []
        self.create_requests: list[dict[str, object]] = []

    def describe_signaling_channel(self, *, ChannelName: str) -> dict[str, object]:
        self.describe_requests.append(ChannelName)
        if ChannelName not in self.channels:
            raise _FakeClientError("ResourceNotFoundException")
        return {"ChannelInfo": {"ChannelName": ChannelName}}

    def create_signaling_channel(self, **kwargs: object) -> dict[str, object]:
        self.create_requests.append(kwargs)
        channel_name = kwargs["ChannelName"]
        assert isinstance(channel_name, str)
        self.channels.add(channel_name)
        return {"ChannelARN": f"arn:aws:kinesisvideo:::channel/{channel_name}"}


class _FakeRuntime:
    def __init__(self) -> None:
        self.region_name = "eu-central-1"
        self.iot = _FakeIotClient()
        self.iot_data = _FakeIotDataClient()
        self.kinesisvideo = _FakeKinesisVideoClient()
        self.client_calls: list[tuple[str, str | None, dict[str, object]]] = []

    def iot_client(self) -> _FakeIotClient:
        return self.iot

    def iot_data_endpoint(self) -> str:
        return "abc123-ats.iot.eu-central-1.amazonaws.com"

    def client(
        self,
        service_name: str,
        *,
        region_name: str | None = None,
        **kwargs: object,
    ) -> object:
        self.client_calls.append((service_name, region_name, kwargs))
        if service_name == "iot-data":
            return self.iot_data
        if service_name == "kinesisvideo":
            return self.kinesisvideo
        raise AssertionError(f"unexpected client request: {service_name}")


class DeviceRegistryTests(unittest.TestCase):
    def test_register_town_creates_new_town_and_initializes_reported_only_shadow(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("town01"),
        )

        registration = registry.register_town(town_name="Berlin")

        self.assertEqual(registration.thing_name, "town-town01")
        self.assertEqual(registration.thing_type, "town")
        self.assertEqual(registration.name, "berlin")
        self.assertEqual(registration.short_id, "town01")
        self.assertEqual(
            runtime.iot.create_thing_requests[0],
            {
                "thingName": "town-town01",
                "thingTypeName": "town",
                "attributePayload": {
                    "attributes": {
                        "name": "berlin",
                        "shortId": "town01",
                        "capabilitiesSet": "sparkplug",
                    }
                },
            },
        )
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "berlin")
        self.assertEqual(
            runtime.iot.create_group_requests[0]["queryString"],
            "thingTypeName:rig AND attributes.town:berlin",
        )
        self.assertEqual(
            runtime.iot.create_thing_type_requests[0]["thingTypeProperties"]["searchableAttributes"],
            ["name"],
        )
        self.assertEqual(runtime.iot_data.update_requests[0][0:2], ("town-town01", "sparkplug"))
        self.assertEqual(
            json.loads(runtime.iot_data.update_requests[0][2]),
            {
                "state": {
                    "reported": {
                        "session": {
                            "entityKind": "group",
                            "groupId": "berlin",
                            "online": True,
                        },
                        "metrics": {"redcon": 1},
                    }
                }
            },
        )

    def test_register_rig_creates_new_rig_and_initializes_reported_only_shadow(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("rig002"),
        )
        runtime.iot.groups.add("berlin")

        registration = registry.register_rig(
            town_name="Berlin",
            rig_name="Rig-A",
        )

        self.assertEqual(registration.thing_name, "rig-rig002")
        self.assertEqual(registration.thing_type, "rig")
        self.assertEqual(registration.name, "rig-a")
        self.assertEqual(registration.short_id, "rig002")
        self.assertEqual(registration.town_name, "berlin")
        self.assertEqual(
            runtime.iot.create_thing_requests[0],
            {
                "thingName": "rig-rig002",
                "thingTypeName": "rig",
                "attributePayload": {
                    "attributes": {
                        "name": "rig-a",
                        "shortId": "rig002",
                        "town": "berlin",
                        "capabilitiesSet": "sparkplug",
                    }
                },
            },
        )
        self.assertEqual(
            runtime.iot.create_thing_type_requests[0]["thingTypeProperties"]["searchableAttributes"],
            ["name", "town"],
        )
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "rig-a")
        self.assertEqual(
            runtime.iot.create_group_requests[0]["queryString"],
            "attributes.rig:rig-a AND attributes.town:*",
        )
        self.assertEqual(runtime.iot_data.update_requests[0][0:2], ("rig-rig002", "sparkplug"))
        self.assertEqual(
            json.loads(runtime.iot_data.update_requests[0][2]),
            {
                "state": {
                    "reported": {
                        "session": {
                            "entityKind": "node",
                            "groupId": "berlin",
                            "edgeNodeId": "rig-a",
                            "messageType": "NDEATH",
                            "online": False,
                        },
                        "metrics": {},
                    }
                }
            },
        )

    def test_register_rig_falls_back_to_registry_when_town_is_not_yet_indexed(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot.groups.add("berlin")
        runtime.iot.search_visible_thing_names = {"unit-aaaaaa", "unit-z9x8w7"}
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("rig002"),
        )

        registration = registry.register_rig(
            town_name="Berlin",
            rig_name="Rig-A",
        )

        self.assertEqual(registration.thing_name, "rig-rig002")
        self.assertEqual(runtime.iot.list_things_requests, [{"maxResults": 100}])

    def test_register_device_creates_new_unit_device_and_initializes_resources(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot.groups.update({"berlin", "rig-a"})
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("aaaaaabbbbbb"),
        )

        registration = registry.register_device(
            town_name="Berlin",
            rig_name="Rig-A",
            device_type="unit",
        )

        self.assertEqual(registration.device_id, "unit-bbbbbb")
        self.assertEqual(registration.thing_name, "unit-bbbbbb")
        self.assertEqual(registration.thing_type, "unit")
        self.assertEqual(registration.town_name, "berlin")
        self.assertEqual(registration.rig_name, "rig-a")
        self.assertEqual(registration.name, "bot")
        self.assertEqual(registration.short_id, "bbbbbb")
        self.assertEqual(
            runtime.iot.create_thing_requests[0],
            {
                "thingName": "unit-bbbbbb",
                "thingTypeName": "unit",
                "attributePayload": {
                    "attributes": {
                        "town": "berlin",
                        "rig": "rig-a",
                        "name": "bot",
                        "shortId": "bbbbbb",
                        "capabilitiesSet": "sparkplug,mcu,board,mcp,video",
                    }
                },
            },
        )
        self.assertEqual(
            runtime.iot.create_thing_type_requests[0],
            {
                "thingTypeName": "unit",
                "thingTypeProperties": {
                    "thingTypeDescription": "Registered txing device type unit",
                    "searchableAttributes": [
                        "name",
                        "town",
                        "rig",
                    ],
                },
            },
        )
        self.assertEqual(
            runtime.iot_data.get_requests,
            [
                ("unit-bbbbbb", "sparkplug"),
                ("unit-bbbbbb", "mcu"),
                ("unit-bbbbbb", "board"),
                ("unit-bbbbbb", "mcp"),
                ("unit-bbbbbb", "video"),
            ],
        )
        self.assertEqual(runtime.iot_data.update_requests[0][0], "unit-bbbbbb")
        self.assertEqual(runtime.iot_data.update_requests[0][1], "sparkplug")
        self.assertTrue(runtime.iot_data.update_requests[0][2].startswith(b"{"))
        self.assertEqual(
            runtime.kinesisvideo.create_requests[0]["ChannelName"],
            "unit-bbbbbb-board-video",
        )

    def test_register_device_falls_back_to_registry_when_town_and_rig_are_not_yet_indexed(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot.groups.update({"berlin", "rig-a"})
        runtime.iot.search_visible_thing_names = {"unit-aaaaaa", "unit-z9x8w7"}
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("aaaaaabbbbbb"),
        )

        registration = registry.register_device(
            town_name="Berlin",
            rig_name="Rig-A",
            device_type="unit",
        )

        self.assertEqual(registration.device_id, "unit-bbbbbb")
        self.assertEqual(len(runtime.iot.list_things_requests), 2)

    def test_register_device_rejects_non_loadable_device_type(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(runtime, repo_root=REPO_ROOT)

        with self.assertRaises(DeviceTypeNotFoundError):
            registry.register_device(
                town_name="berlin",
                rig_name="rig-a",
                device_type="template",
            )

    def test_assign_device_updates_town_and_rig_without_renaming_the_thing(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot.groups.update({"berlin", "munich", "rig-b"})
        runtime.iot._things["town-muc001"] = {
            "thingName": "town-muc001",
            "thingTypeName": "town",
                "attributes": {
                    "name": "munich",
                    "shortId": "muc001",
                    "capabilitiesSet": "sparkplug",
                },
            "version": 1,
        }
        runtime.iot._things["rig-rig002"] = {
            "thingName": "rig-rig002",
            "thingTypeName": "rig",
                "attributes": {
                    "name": "rig-b",
                    "shortId": "rig002",
                    "town": "munich",
                    "capabilitiesSet": "sparkplug",
                },
            "version": 1,
        }
        registry = AwsDeviceRegistry(runtime, repo_root=REPO_ROOT)

        registration = registry.assign_device(
            "unit-z9x8w7",
            town_name="munich",
            rig_name="rig-b",
        )

        self.assertEqual(
            runtime.iot.update_thing_requests[0],
            {
                "thingName": "unit-z9x8w7",
                "attributePayload": {
                    "attributes": {
                        "town": "munich",
                        "rig": "rig-b",
                    },
                    "merge": True,
                },
                "expectedVersion": 7,
            },
        )
        self.assertEqual(registration.device_id, "unit-z9x8w7")
        self.assertEqual(registration.thing_name, "unit-z9x8w7")
        self.assertEqual(registration.thing_type, "unit")
        self.assertEqual(registration.town_name, "munich")
        self.assertEqual(registration.rig_name, "rig-b")
        self.assertEqual(registration.name, "bot")

    def test_register_device_rejects_existing_thing_type_without_required_searchable_attributes(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot.thing_types["unit"] = {
            "thingTypeDescription": "Registered txing device type unit",
            "searchableAttributes": ["name", "town"],
        }
        registry = AwsDeviceRegistry(runtime, repo_root=REPO_ROOT)

        with self.assertRaisesRegex(
            RuntimeError,
            "already exists without required searchableAttributes",
        ):
            registry.register_device(
                town_name="berlin",
                rig_name="rig-a",
                device_type="unit",
            )


if __name__ == "__main__":
    unittest.main()
