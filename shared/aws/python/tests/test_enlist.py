from __future__ import annotations

import json
from pathlib import Path
import random
import re
import unittest
from unittest.mock import patch
from typing import Any

from aws.type_catalog import SsmTypeCatalog
from aws_admin import enlist_txing as enlist


REPO_ROOT = Path(__file__).resolve().parents[4]
IOT_ATTRIBUTE_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_.,@/:#=\[\]-]*$")


class _FakeAwsError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.response = {"Error": {"Code": code, "Message": message or code}}


class _FakeSsmClient:
    def __init__(self) -> None:
        self.parameters: dict[str, str] = {}
        self.parameter_err: Exception | None = None

    def get_parameters_by_path(self, **kwargs: object) -> dict[str, object]:
        if self.parameter_err is not None:
            raise self.parameter_err
        path = str(kwargs["Path"]).rstrip("/")
        prefix = f"{path}/"
        rows = [
            {"Name": name, "Value": self.parameters[name]}
            for name in sorted(self.parameters)
            if name.startswith(prefix)
        ]
        return {"Parameters": rows}

    def put_parameter(self, **kwargs: object) -> None:
        self.parameters[str(kwargs["Name"])] = str(kwargs["Value"])

    def delete_parameters(self, *, Names: list[str]) -> dict[str, object]:
        for name in Names:
            self.parameters.pop(name, None)
        return {"DeletedParameters": Names, "InvalidParameters": []}


class _FakeIotClient:
    def __init__(self) -> None:
        self.things: dict[str, dict[str, Any]] = {}
        self.principals: dict[str, list[str]] = {}
        self.thing_groups: dict[str, set[str]] = {}
        self.search_page_size = 0

    def describe_thing(self, *, thingName: str) -> dict[str, Any]:
        thing = self.things.get(thingName)
        if thing is None:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName} not found")
        return {
            "thingName": thing["thingName"],
            "thingTypeName": thing["thingTypeName"],
            "attributes": dict(thing["attributes"]),
            "version": thing["version"],
        }

    def create_thing(
        self,
        *,
        thingName: str,
        thingTypeName: str,
        attributePayload: dict[str, Any],
    ) -> dict[str, Any]:
        if thingName in self.things:
            raise _FakeAwsError("ResourceAlreadyExistsException", f"{thingName} exists")
        attributes = dict(attributePayload.get("attributes", {}))
        self._validate_attributes(attributes)
        self.things[thingName] = {
            "thingName": thingName,
            "thingTypeName": thingTypeName,
            "attributes": attributes,
            "version": 1,
        }
        return {"thingName": thingName}

    def update_thing(
        self,
        *,
        thingName: str,
        attributePayload: dict[str, Any],
        expectedVersion: int | None = None,
    ) -> dict[str, Any]:
        thing = self.things.get(thingName)
        if thing is None:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName} not found")
        if expectedVersion is not None and expectedVersion != thing["version"]:
            raise _FakeAwsError("VersionConflictException", "version conflict")
        attributes = dict(attributePayload.get("attributes", {}))
        self._validate_attributes(attributes)
        if attributePayload.get("merge", False):
            thing["attributes"].update(attributes)
        else:
            thing["attributes"] = attributes
        thing["version"] += 1
        return {}

    def delete_thing(self, *, thingName: str) -> dict[str, object]:
        if thingName not in self.things:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName} not found")
        if self.principals.get(thingName):
            raise _FakeAwsError("InvalidRequestException", "principals are still attached")
        del self.things[thingName]
        self.principals.pop(thingName, None)
        for members in self.thing_groups.values():
            members.discard(thingName)
        return {}

    def search_index(self, **kwargs: object) -> dict[str, object]:
        query = str(kwargs["queryString"])
        predicates = [part.strip() for part in query.split(" AND ")]
        matches: list[dict[str, str]] = []
        for thing in self.things.values():
            if all(self._matches(thing, predicate) for predicate in predicates):
                matches.append({"thingName": thing["thingName"]})
        matches.sort(key=lambda item: item["thingName"])
        start = int(str(kwargs.get("nextToken") or "0"))
        if self.search_page_size > 0:
            end = min(len(matches), start + self.search_page_size)
            response: dict[str, object] = {"things": matches[start:end]}
            if end < len(matches):
                response["nextToken"] = str(end)
            return response
        return {"things": matches[start:]}

    def list_thing_principals(self, *, thingName: str, **_kwargs: object) -> dict[str, object]:
        if thingName not in self.things:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName} not found")
        return {"principals": list(self.principals.get(thingName, []))}

    def detach_thing_principal(self, *, thingName: str, principal: str) -> dict[str, object]:
        principals = self.principals.setdefault(thingName, [])
        if principal in principals:
            principals.remove(principal)
        return {}

    def create_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
        if thingGroupName in self.thing_groups:
            raise _FakeAwsError("ResourceAlreadyExistsException", f"{thingGroupName} exists")
        self.thing_groups[thingGroupName] = set()
        return {}

    def list_thing_groups_for_thing(self, *, thingName: str, **_kwargs: object) -> dict[str, object]:
        groups = [
            {"groupName": group_name}
            for group_name, members in sorted(self.thing_groups.items())
            if thingName in members
        ]
        return {"thingGroups": groups}

    def add_thing_to_thing_group(self, *, thingName: str, thingGroupName: str) -> dict[str, object]:
        if thingName not in self.things:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName} not found")
        self.thing_groups.setdefault(thingGroupName, set()).add(thingName)
        return {}

    def remove_thing_from_thing_group(self, *, thingName: str, thingGroupName: str) -> dict[str, object]:
        self.thing_groups.setdefault(thingGroupName, set()).discard(thingName)
        return {}

    @staticmethod
    def _validate_attributes(attributes: dict[str, Any]) -> None:
        for key, value in attributes.items():
            if not isinstance(value, str) or not IOT_ATTRIBUTE_VALUE_PATTERN.fullmatch(value):
                raise _FakeAwsError("InvalidRequestException", f"invalid attribute {key}={value!r}")

    @staticmethod
    def _matches(thing: dict[str, Any], predicate: str) -> bool:
        key, _, value = predicate.partition(":")
        if key == "thingTypeName":
            return value == "*" or thing["thingTypeName"] == value
        if key.startswith("attributes."):
            attribute_name = key.removeprefix("attributes.")
            attribute_value = thing["attributes"].get(attribute_name)
            return value == "*" and attribute_value is not None or attribute_value == value
        return False


class _FakeIotDataClient:
    def __init__(self) -> None:
        self.shadows: dict[tuple[str, str], bytes] = {}
        self.update_calls: list[tuple[str, str, bytes]] = []

    def get_thing_shadow(self, *, thingName: str, shadowName: str) -> dict[str, bytes]:
        key = (thingName, shadowName)
        if key not in self.shadows:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName}/{shadowName} not found")
        return {"payload": self.shadows[key]}

    def update_thing_shadow(self, *, thingName: str, shadowName: str, payload: bytes) -> dict[str, Any]:
        key = (thingName, shadowName)
        self.shadows[key] = payload
        self.update_calls.append((thingName, shadowName, payload))
        return {}

    def delete_thing_shadow(self, *, thingName: str, shadowName: str) -> dict[str, Any]:
        key = (thingName, shadowName)
        if key not in self.shadows:
            raise _FakeAwsError("ResourceNotFoundException", f"{thingName}/{shadowName} not found")
        del self.shadows[key]
        return {}


class _FakeKinesisVideoClient:
    def __init__(self) -> None:
        self.channels: set[str] = set()

    def describe_signaling_channel(self, *, ChannelName: str) -> dict[str, Any]:
        if ChannelName not in self.channels:
            raise _FakeAwsError("ResourceNotFoundException", f"{ChannelName} not found")
        return {
            "ChannelInfo": {
                "ChannelName": ChannelName,
                "ChannelARN": f"arn:aws:kinesisvideo:eu-central-1:123:channel/{ChannelName}/1",
            }
        }

    def create_signaling_channel(self, *, ChannelName: str, **_kwargs: Any) -> dict[str, str]:
        self.channels.add(ChannelName)
        return {"ChannelARN": f"arn:aws:kinesisvideo:eu-central-1:123:channel/{ChannelName}/1"}


class _FakeRuntime:
    region_name = "eu-central-1"

    def __init__(self) -> None:
        self.iot = _FakeIotClient()
        self.iot_data = _FakeIotDataClient()
        self.ssm = _FakeSsmClient()
        self.kinesisvideo = _FakeKinesisVideoClient()

    def iot_client(self) -> _FakeIotClient:
        return self.iot

    def iot_data_endpoint(self) -> str:
        return "example.iot.eu-central-1.amazonaws.com"

    def client(self, service_name: str, **_kwargs: object) -> object:
        if service_name == "ssm":
            return self.ssm
        if service_name == "iot-data":
            return self.iot_data
        if service_name == "kinesisvideo":
            return self.kinesisvideo
        raise AssertionError(f"unexpected client: {service_name}")


class EnlistServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = _FakeRuntime()
        self.catalog = SsmTypeCatalog(self.runtime.ssm, repo_root=REPO_ROOT)
        self.catalog.sync()
        self.service = enlist.EnlistService(
            self.runtime,
            random_source=random.Random(11),
            type_catalog=self.catalog,
        )

    def _enlist_town(self) -> dict[str, Any]:
        return self.service.handle({"action": "enlistTown", "townName": "town"})

    def _enlist_rig(self, town_id: str, rig_type: str, rig_name: str) -> dict[str, Any]:
        return self.service.handle(
            {
                "action": "enlistRig",
                "townId": town_id,
                "rigType": rig_type,
                "rigName": rig_name,
            }
        )

    def _enlist_device(self, rig_id: str, device_type: str, device_name: str) -> dict[str, Any]:
        return self.service.handle(
            {
                "action": "enlistDevice",
                "rigId": rig_id,
                "deviceType": device_type,
                "deviceName": device_name,
            }
        )

    def test_enlist_town_creates_attributes_and_sparkplug_shadow(self) -> None:
        result = self._enlist_town()

        self.assertTrue(result["created"])
        self.assertEqual(result["thingTypeName"], "town")
        self.assertRegex(result["thingName"], r"^town-[0-9a-z]{6}$")
        self.assertEqual(result["attributes"]["kind"], "townType")
        self.assertEqual(result["attributes"]["capabilities"], "sparkplug")
        self.assertEqual(result["initializedShadows"], ["sparkplug"])
        shadow = json.loads(self.runtime.iot_data.shadows[(result["thingName"], "sparkplug")])
        self.assertEqual(shadow["state"]["reported"]["payload"]["metrics"]["redcon"], 1)

    def test_enlist_rigs_use_type_catalog_and_repair_type_group_membership(self) -> None:
        town = self._enlist_town()
        cloud = self._enlist_rig(town["thingName"], "cloud", "aws")
        raspi = self._enlist_rig(town["thingName"], "raspi", "server")

        self.assertEqual(cloud["thingTypeName"], "cloud")
        self.assertEqual(cloud["attributes"]["kind"], "rigType")
        self.assertEqual(cloud["attributes"]["rigType"], "cloud")
        self.assertEqual(cloud["attributes"]["townId"], town["thingName"])
        self.assertEqual(cloud["auxiliaryResources"]["thingGroupName"], "txing-rig-type-cloud")
        self.assertIn(cloud["thingName"], self.runtime.iot.thing_groups["txing-rig-type-cloud"])
        self.assertEqual(raspi["attributes"]["hostServices"], "bluetooth.service")

        thing_name = cloud["thingName"]
        self.runtime.iot.thing_groups.setdefault("txing-rig-type-raspi", set()).add(thing_name)
        repaired = self._enlist_rig(town["thingName"], "cloud", "aws")
        self.assertFalse(repaired["created"])
        self.assertIn(thing_name, self.runtime.iot.thing_groups["txing-rig-type-cloud"])
        self.assertNotIn(thing_name, self.runtime.iot.thing_groups["txing-rig-type-raspi"])

    def test_enlist_cloud_mcu_validates_compatibility_and_initializes_shadows(self) -> None:
        town = self._enlist_town()
        raspi = self._enlist_rig(town["thingName"], "raspi", "server")
        with self.assertRaisesRegex(enlist.EnlistError, "not compatible"):
            self._enlist_device(raspi["thingName"], "cloud-mcu", "cloud")

        cloud = self._enlist_rig(town["thingName"], "cloud", "aws")
        result = self._enlist_device(cloud["thingName"], "cloud-mcu", "cloud")

        self.assertEqual(result["thingTypeName"], "cloud-mcu")
        self.assertEqual(result["attributes"]["kind"], "deviceType")
        self.assertEqual(result["attributes"]["rigType"], "cloud")
        self.assertEqual(result["attributes"]["deviceType"], "cloud-mcu")
        self.assertEqual(result["attributes"]["webAdapter"], "web/cloud-mcu-adapter.tsx")
        self.assertEqual(result["attributes"]["capabilities"], "sparkplug,sqs,power,ecs")
        self.assertEqual(result["attributes"]["redconCommandLevels"], "4,3")
        self.assertEqual(result["initializedShadows"], ["sparkplug", "sqs", "power", "ecs"])

    def test_enlist_unit_creates_all_shadows_and_board_video_channel(self) -> None:
        town = self._enlist_town()
        raspi = self._enlist_rig(town["thingName"], "raspi", "server")

        result = self._enlist_device(raspi["thingName"], "unit", "bot")

        self.assertEqual(result["thingTypeName"], "unit")
        self.assertEqual(result["attributes"]["redconCommandLevels"], "4,3,2,1")
        self.assertEqual(
            result["initializedShadows"],
            ["sparkplug", "ble", "power", "board", "mcp", "video"],
        )
        board_video = result["auxiliaryResources"]["boardVideo"]
        self.assertIn(result["thingName"], board_video["channelName"])
        self.assertTrue(board_video["created"])
        self.assertIn(board_video["channelName"], self.runtime.kinesisvideo.channels)

    def test_repeated_enlist_repairs_attrs_without_replacing_shadows(self) -> None:
        town = self._enlist_town()
        cloud = self._enlist_rig(town["thingName"], "cloud", "aws")
        first = self._enlist_device(cloud["thingName"], "cloud-mcu", "cloud")
        thing_name = first["thingName"]
        self.runtime.iot.things[thing_name]["attributes"].pop("webAdapter")
        self.runtime.iot_data.shadows[(thing_name, "sqs")] = b'{"state":{"reported":{"custom":true}}}'
        update_count = len(self.runtime.iot_data.update_calls)

        second = self._enlist_device(cloud["thingName"], "cloud-mcu", "cloud")

        self.assertFalse(second["created"])
        self.assertEqual(second["initializedShadows"], [])
        self.assertEqual(second["attributes"]["webAdapter"], "web/cloud-mcu-adapter.tsx")
        self.assertEqual(len(self.runtime.iot_data.update_calls), update_count)

    def test_assign_device_validates_compatibility_and_does_not_reset_shadows(self) -> None:
        town = self._enlist_town()
        cloud_a = self._enlist_rig(town["thingName"], "cloud", "aws")
        cloud_b = self._enlist_rig(town["thingName"], "cloud", "backup")
        device = self._enlist_device(cloud_a["thingName"], "cloud-mcu", "cloud")
        update_count = len(self.runtime.iot_data.update_calls)

        result = self.service.handle(
            {
                "action": "assignDevice",
                "deviceId": device["thingName"],
                "rigId": cloud_b["thingName"],
            }
        )

        self.assertFalse(result["created"])
        self.assertEqual(result["initializedShadows"], [])
        self.assertEqual(result["attributes"]["rigId"], cloud_b["thingName"])
        self.assertEqual(len(self.runtime.iot_data.update_calls), update_count)

    def test_discharge_thing_deletes_shadows_principals_and_thing(self) -> None:
        town = self._enlist_town()
        raspi = self._enlist_rig(town["thingName"], "raspi", "server")
        device = self._enlist_device(raspi["thingName"], "unit", "bot")
        thing_name = device["thingName"]
        self.runtime.iot.principals[thing_name] = [
            "arn:aws:iot:eu-central-1:123:cert/one",
            "arn:aws:iot:eu-central-1:123:cert/two",
        ]

        result = self.service.handle({"action": "dischargeThing", "thingId": thing_name})

        self.assertTrue(result["deleted"])
        self.assertEqual(result["thingName"], thing_name)
        self.assertEqual(
            result["deletedShadows"],
            ["sparkplug", "ble", "power", "board", "mcp", "video"],
        )
        self.assertEqual(
            result["detachedPrincipals"],
            [
                "arn:aws:iot:eu-central-1:123:cert/one",
                "arn:aws:iot:eu-central-1:123:cert/two",
            ],
        )
        self.assertNotIn(thing_name, self.runtime.iot.things)
        self.assertEqual(result["auxiliaryResources"], {})

    def test_discharge_all_deletes_devices_then_rigs_then_towns_with_paginated_search(self) -> None:
        self.runtime.iot.search_page_size = 1
        town = self._enlist_town()
        cloud = self._enlist_rig(town["thingName"], "cloud", "aws")
        device = self._enlist_device(cloud["thingName"], "cloud-mcu", "cloud")

        result = self.service.handle({"action": "dischargeAll"})

        self.assertEqual(result["deletedThingCount"], 3)
        self.assertEqual(
            [row["thingName"] for row in result["deletedThings"]],
            [device["thingName"], cloud["thingName"], town["thingName"]],
        )
        self.assertEqual(self.runtime.iot.things, {})

    def test_malformed_events_and_aws_errors_return_lambda_error_envelopes(self) -> None:
        with (
            patch.object(enlist, "resolve_aws_region", return_value="eu-central-1"),
            patch.object(enlist, "build_aws_runtime", return_value=self.runtime),
        ):
            unsupported = enlist.lambda_handler({"action": "unsupported"}, object())
            self.assertEqual(unsupported["ok"], False)
            self.assertEqual(unsupported["errorType"], "EnlistError")
            self.assertEqual(unsupported["message"], "unsupported enlist action: 'unsupported'")

            self.runtime.ssm.parameter_err = RuntimeError("ssm failed")
            failed = enlist.lambda_handler({"action": "enlistTown", "townName": "town"}, object())
            self.assertEqual(failed["ok"], False)
            self.assertEqual(failed["errorType"], "Error")
            self.assertIn("ssm failed", failed["message"])

    def test_cfn_create_update_delete_never_discharges_things_and_failure_sends_failed(self) -> None:
        town = self._enlist_town()
        cloud = self._enlist_rig(town["thingName"], "cloud", "aws")
        self._enlist_device(cloud["thingName"], "cloud-mcu", "cloud")
        sent: list[tuple[str, dict[str, Any], str | None, str | None]] = []

        def send_response(
            event: dict[str, Any],
            context: object,
            status: str,
            *,
            data: dict[str, Any] | None = None,
            reason: str | None = None,
            physical_resource_id: str | None = None,
        ) -> None:
            sent.append((status, dict(data or {}), reason, physical_resource_id))

        with (
            patch.object(enlist, "_send_cfn_response", side_effect=send_response),
        ):
            create = enlist.lambda_handler(_cfn_event("Create", "TxingDischargeThings"), object())
            delete = enlist.lambda_handler(_cfn_event("Delete", "TxingDischargeThings"), object())
            failed = enlist.lambda_handler(_cfn_event("Delete", "Wrong"), object())

        self.assertEqual(create["ok"], True)
        self.assertEqual(create["skipped"], True)
        self.assertEqual(delete["ok"], True)
        self.assertEqual(delete["skipped"], True)
        self.assertEqual(len(self.runtime.iot.things), 3)
        self.assertEqual(failed["ok"], False)
        self.assertEqual(failed["errorType"], "EnlistError")
        self.assertEqual([row[0] for row in sent], ["SUCCESS", "SUCCESS", "FAILED"])
        self.assertEqual(sent[2][3], "txing-discharge-things-on-delete")


def _cfn_event(request_type: str, cleanup_type: str) -> dict[str, Any]:
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cloudformation-response.example",
        "StackId": "stack",
        "RequestId": "request",
        "LogicalResourceId": "TxingDischargeThingsOnStackDelete",
        "ResourceProperties": {
            "CleanupType": cleanup_type,
            "PhysicalResourceId": "txing-discharge-things-on-delete",
        },
    }


if __name__ == "__main__":
    unittest.main()
