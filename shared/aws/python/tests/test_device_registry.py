from __future__ import annotations

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
        self.describe_group_requests: list[str] = []
        self.create_group_requests: list[dict[str, object]] = []
        self.update_group_requests: list[dict[str, object]] = []
        self.groups: set[str] = set()
        self._things: dict[str, dict[str, object]] = {
            "unit-aaaaaa": {
                "thingName": "unit-aaaaaa",
                "attributes": {
                    "town": "berlin",
                    "rig": "rig-a",
                    "deviceType": "unit",
                    "deviceName": "bot",
                    "shortId": "aaaaaa",
                },
                "version": 1,
            },
            "unit-z9x8w7": {
                "thingName": "unit-z9x8w7",
                "attributes": {
                    "town": "berlin",
                    "rig": "rig-a",
                    "deviceType": "unit",
                    "deviceName": "bot",
                    "shortId": "z9x8w7",
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
        self._things[thing_name] = {
            "thingName": thing_name,
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


class _FakeIotDataClient:
    def __init__(self) -> None:
        self.shadows: dict[str, bytes] = {}
        self.get_requests: list[str] = []
        self.update_requests: list[tuple[str, bytes]] = []

    def get_thing_shadow(self, *, thingName: str) -> dict[str, object]:
        self.get_requests.append(thingName)
        try:
            payload = self.shadows[thingName]
        except KeyError as err:
            raise _FakeClientError("ResourceNotFoundException") from err
        return {"payload": payload}

    def update_thing_shadow(self, *, thingName: str, payload: bytes) -> dict[str, object]:
        self.update_requests.append((thingName, payload))
        self.shadows[thingName] = payload
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
    def test_register_device_creates_new_unit_device_and_initializes_resources(self) -> None:
        runtime = _FakeRuntime()
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
        self.assertEqual(registration.town_name, "berlin")
        self.assertEqual(registration.rig_name, "rig-a")
        self.assertEqual(registration.device_type, "unit")
        self.assertEqual(registration.device_name, "bot")
        self.assertEqual(registration.short_id, "bbbbbb")
        self.assertEqual(
            runtime.iot.create_thing_requests[0],
            {
                "thingName": "unit-bbbbbb",
                "attributePayload": {
                    "attributes": {
                        "town": "berlin",
                        "rig": "rig-a",
                        "deviceType": "unit",
                        "deviceName": "bot",
                        "shortId": "bbbbbb",
                    }
                },
            },
        )
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "rig-a")
        self.assertEqual(runtime.iot_data.get_requests, ["unit-bbbbbb"])
        self.assertEqual(runtime.iot_data.update_requests[0][0], "unit-bbbbbb")
        self.assertTrue(runtime.iot_data.update_requests[0][1].startswith(b"{"))
        self.assertEqual(
            runtime.kinesisvideo.create_requests[0]["ChannelName"],
            "unit-bbbbbb-board-video",
        )

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
        runtime.iot.groups.add("rig-a")
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
        self.assertEqual(registration.town_name, "munich")
        self.assertEqual(registration.rig_name, "rig-b")
        self.assertEqual(registration.device_type, "unit")
        self.assertEqual(registration.device_name, "bot")
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "rig-b")


if __name__ == "__main__":
    unittest.main()
