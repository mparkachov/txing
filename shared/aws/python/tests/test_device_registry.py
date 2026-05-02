from __future__ import annotations

from pathlib import Path
import unittest

from aws.device_registry import AwsDeviceRegistry, DeviceRegistryError
from aws.type_catalog import SsmTypeCatalog, build_type_records


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


class _FakeSsmClient:
    def __init__(self, records: dict[str, dict[str, object]] | None = None) -> None:
        self.parameters: dict[str, str] = {}
        self.put_requests: list[dict[str, object]] = []
        catalog = SsmTypeCatalog(self, repo_root=REPO_ROOT)
        for path, record in (records or build_type_records(repo_root=REPO_ROOT)).items():
            catalog.put_record(path, record)
        self.put_requests.clear()

    def get_parameter(self, *, Name: str) -> dict[str, object]:
        try:
            value = self.parameters[Name]
        except KeyError as err:
            raise _FakeClientError("ParameterNotFound") from err
        return {"Parameter": {"Name": Name, "Value": value}}

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
        for name in Names:
            self.parameters.pop(name, None)
        return {"DeletedParameters": Names, "InvalidParameters": []}


class _FakeIotClient:
    def __init__(self) -> None:
        self.create_thing_requests: list[dict[str, object]] = []
        self.update_thing_requests: list[dict[str, object]] = []
        self.create_group_requests: list[dict[str, object]] = []
        self.update_group_requests: list[dict[str, object]] = []
        self.create_thing_type_requests: list[dict[str, object]] = []
        self.thing_types: dict[str, dict[str, object]] = {}
        self.groups: set[str] = set()
        self._things: dict[str, dict[str, object]] = {
            "town-ber001": {
                "thingName": "town-ber001",
                "thingTypeName": "town",
                "attributes": {
                    "name": "berlin",
                    "shortId": "ber001",
                    "capabilities": "sparkplug",
                },
                "version": 1,
            },
            "rig-ras001": {
                "thingName": "rig-ras001",
                "thingTypeName": "rig",
                "attributes": {
                    "name": "server",
                    "shortId": "ras001",
                    "townId": "town-ber001",
                    "rigType": "raspi",
                    "capabilities": "sparkplug",
                },
                "version": 1,
            },
            "rig-cld001": {
                "thingName": "rig-cld001",
                "thingTypeName": "rig",
                "attributes": {
                    "name": "aws",
                    "shortId": "cld001",
                    "townId": "town-ber001",
                    "rigType": "cloud",
                    "capabilities": "sparkplug",
                },
                "version": 1,
            },
            "unit-aaaaaa": {
                "thingName": "unit-aaaaaa",
                "thingTypeName": "unit",
                "attributes": {
                    "name": "bot",
                    "shortId": "aaaaaa",
                    "townId": "town-ber001",
                    "rigId": "rig-ras001",
                    "deviceType": "unit",
                    "capabilities": "sparkplug,mcu,board,mcp,video",
                },
                "version": 1,
            },
        }

    def describe_thing(self, *, thingName: str) -> dict[str, object]:
        try:
            thing = self._things[thingName]
        except KeyError as err:
            raise _FakeClientError("ResourceNotFoundException") from err
        return {
            **thing,
            "attributes": dict(thing["attributes"]),  # type: ignore[arg-type]
        }

    def create_thing(self, **kwargs: object) -> dict[str, object]:
        self.create_thing_requests.append(kwargs)
        attributes = kwargs["attributePayload"]["attributes"]  # type: ignore[index]
        thing_name = str(kwargs["thingName"])
        self._things[thing_name] = {
            "thingName": thing_name,
            "thingTypeName": str(kwargs["thingTypeName"]),
            "attributes": dict(attributes),  # type: ignore[arg-type]
            "version": 1,
        }
        return {"thingName": thing_name}

    def update_thing(self, **kwargs: object) -> dict[str, object]:
        self.update_thing_requests.append(kwargs)
        thing_name = str(kwargs["thingName"])
        attributes = kwargs["attributePayload"]["attributes"]  # type: ignore[index]
        current = self._things[thing_name]
        merged = dict(current["attributes"])  # type: ignore[arg-type]
        merged.update(attributes)  # type: ignore[arg-type]
        current["attributes"] = merged
        current["version"] = int(current["version"]) + 1
        return {"thingName": thing_name}

    def describe_thing_type(self, *, thingTypeName: str) -> dict[str, object]:
        if thingTypeName not in self.thing_types:
            raise _FakeClientError("ResourceNotFoundException")
        return {"thingTypeProperties": dict(self.thing_types[thingTypeName])}

    def create_thing_type(self, **kwargs: object) -> dict[str, object]:
        self.create_thing_type_requests.append(kwargs)
        self.thing_types[str(kwargs["thingTypeName"])] = dict(kwargs["thingTypeProperties"])  # type: ignore[arg-type]
        return {"thingTypeName": kwargs["thingTypeName"]}

    def describe_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
        if thingGroupName not in self.groups:
            raise _FakeClientError("ResourceNotFoundException")
        return {"thingGroupName": thingGroupName}

    def create_dynamic_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.create_group_requests.append(kwargs)
        self.groups.add(str(kwargs["thingGroupName"]))
        return {"thingGroupName": kwargs["thingGroupName"]}

    def update_dynamic_thing_group(self, **kwargs: object) -> dict[str, object]:
        self.update_group_requests.append(kwargs)
        return {"thingGroupName": kwargs["thingGroupName"]}

    def search_index(self, **kwargs: object) -> dict[str, object]:
        query = str(kwargs["queryString"])
        matches: list[str] = []
        for thing_name, thing in self._things.items():
            attrs = thing["attributes"]
            assert isinstance(attrs, dict)
            thing_type = thing["thingTypeName"]
            if "thingTypeName:town" in query and thing_type != "town":
                continue
            if "thingTypeName:rig" in query and thing_type != "rig":
                continue
            if "thingTypeName:unit" in query and thing_type != "unit":
                continue
            if "thingTypeName:time" in query and thing_type != "time":
                continue
            for key in ("name", "townId", "rigId", "rigType", "deviceType"):
                marker = f"attributes.{key}:"
                if marker in query:
                    expected = query.split(marker, 1)[1].split()[0]
                    if attrs.get(key) != expected:
                        break
            else:
                matches.append(thing_name)
        return {"things": [{"thingName": name} for name in sorted(matches)]}

    def list_things(self, **kwargs: object) -> dict[str, object]:
        return {"things": [{"thingName": name} for name in sorted(self._things)]}


class _FakeIotDataClient:
    def __init__(self) -> None:
        self.shadows: dict[tuple[str, str | None], bytes] = {}
        self.update_requests: list[tuple[str, str | None, bytes]] = []

    def get_thing_shadow(self, *, thingName: str, shadowName: str | None = None) -> dict[str, object]:
        try:
            return {"payload": self.shadows[(thingName, shadowName)]}
        except KeyError as err:
            raise _FakeClientError("ResourceNotFoundException") from err

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
        self.create_requests: list[dict[str, object]] = []

    def describe_signaling_channel(self, *, ChannelName: str) -> dict[str, object]:
        if ChannelName not in self.channels:
            raise _FakeClientError("ResourceNotFoundException")
        return {"ChannelInfo": {"ChannelName": ChannelName}}

    def create_signaling_channel(self, **kwargs: object) -> dict[str, object]:
        self.create_requests.append(kwargs)
        self.channels.add(str(kwargs["ChannelName"]))
        return {"ChannelARN": f"arn:aws:kinesisvideo:::channel/{kwargs['ChannelName']}"}


class _FakeRuntime:
    def __init__(self, *, ssm: _FakeSsmClient | None = None) -> None:
        self.region_name = "eu-central-1"
        self.iot = _FakeIotClient()
        self.ssm = ssm or _FakeSsmClient()
        self.iot_data = _FakeIotDataClient()
        self.kinesisvideo = _FakeKinesisVideoClient()

    def iot_client(self) -> _FakeIotClient:
        return self.iot

    def iot_data_endpoint(self) -> str:
        return "abc123-ats.iot.eu-central-1.amazonaws.com"

    def client(self, service_name: str, **kwargs: object) -> object:
        if service_name == "ssm":
            return self.ssm
        if service_name == "iot-data":
            return self.iot_data
        if service_name == "kinesisvideo":
            return self.kinesisvideo
        raise AssertionError(f"unexpected client request: {service_name}")


class DeviceRegistryTests(unittest.TestCase):
    def test_register_town_writes_new_capabilities_attribute_and_id_group(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("town01"),
        )

        registration = registry.register_town(town_name="Berlin")

        self.assertEqual(registration.thing_name, "town-town01")
        attributes = runtime.iot.create_thing_requests[0]["attributePayload"]["attributes"]  # type: ignore[index]
        self.assertEqual(
            attributes,
            {
                "name": "berlin",
                "shortId": "town01",
                "capabilities": "sparkplug",
            },
        )
        self.assertNotIn("capabilitiesSet", attributes)
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "town-town01")
        self.assertEqual(
            runtime.iot.create_group_requests[0]["queryString"],
            "thingTypeName:rig AND attributes.townId:town-town01",
        )

    def test_register_cloud_rig_copies_type_catalog_parameters_to_iot_attributes(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("rig002"),
        )

        registration = registry.register_rig(
            town_id="town-ber001",
            rig_type="cloud",
            rig_name="AWS",
        )

        self.assertEqual(registration.thing_name, "rig-rig002")
        attributes = runtime.iot.create_thing_requests[0]["attributePayload"]["attributes"]  # type: ignore[index]
        self.assertEqual(
            attributes,
            {
                "name": "aws",
                "shortId": "rig002",
                "townId": "town-ber001",
                "rigType": "cloud",
                "capabilities": "sparkplug",
            },
        )
        self.assertEqual(runtime.iot.create_group_requests[0]["thingGroupName"], "town-ber001")
        self.assertEqual(runtime.iot.create_group_requests[1]["thingGroupName"], "rig-rig002")

    def test_device_enrollment_is_checked_through_ssm_path_compatibility(self) -> None:
        runtime = _FakeRuntime()
        registry = AwsDeviceRegistry(
            runtime,
            repo_root=REPO_ROOT,
            random_source=_SequenceRandom("time01"),
        )

        with self.assertRaisesRegex(DeviceRegistryError, "not compatible"):
            registry.register_device(rig_id="rig-ras001", device_type="time")

        registration = registry.register_device(rig_id="rig-cld001", device_type="time")

        self.assertEqual(registration.thing_name, "time-time01")
        attributes = runtime.iot.create_thing_requests[0]["attributePayload"]["attributes"]  # type: ignore[index]
        self.assertEqual(attributes["townId"], "town-ber001")
        self.assertEqual(attributes["rigId"], "rig-cld001")
        self.assertEqual(attributes["deviceType"], "time")
        self.assertEqual(attributes["capabilities"], "sparkplug,mcp,time")

    def test_assign_device_validates_target_rig_type_before_updating_parent_ids(self) -> None:
        runtime = _FakeRuntime()
        runtime.iot._things["rig-ras002"] = {
            "thingName": "rig-ras002",
            "thingTypeName": "rig",
            "attributes": {
                "name": "server-b",
                "shortId": "ras002",
                "townId": "town-ber001",
                "rigType": "raspi",
                "capabilities": "sparkplug",
            },
            "version": 1,
        }
        runtime.iot._things["time-zzzzzz"] = {
            "thingName": "time-zzzzzz",
            "thingTypeName": "time",
            "attributes": {
                "name": "clock",
                "shortId": "zzzzzz",
                "townId": "town-ber001",
                "rigId": "rig-cld001",
                "deviceType": "time",
                "capabilities": "sparkplug,mcp,time",
            },
            "version": 2,
        }
        registry = AwsDeviceRegistry(runtime, repo_root=REPO_ROOT)

        with self.assertRaisesRegex(DeviceRegistryError, "not compatible"):
            registry.assign_device("time-zzzzzz", rig_id="rig-ras002")

        registration = registry.assign_device("unit-aaaaaa", rig_id="rig-ras002")

        self.assertEqual(registration.rig_id, "rig-ras002")
        self.assertEqual(
            runtime.iot.update_thing_requests[-1]["attributePayload"],
            {
                "attributes": {
                    "townId": "town-ber001",
                    "rigId": "rig-ras002",
                    "deviceType": "unit",
                    "capabilities": "sparkplug,mcu,board,mcp,video",
                },
                "merge": True,
            },
        )

    def test_missing_ssm_compatibility_path_fails_clearly(self) -> None:
        records = build_type_records(repo_root=REPO_ROOT)
        records.pop("/txing/town/cloud/time")
        runtime = _FakeRuntime(ssm=_FakeSsmClient(records))
        registry = AwsDeviceRegistry(runtime, repo_root=REPO_ROOT)

        with self.assertRaisesRegex(DeviceRegistryError, "/txing/town/cloud/time"):
            registry.register_device(rig_id="rig-cld001", device_type="time")


if __name__ == "__main__":
    unittest.main()
