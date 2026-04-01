from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class ThingRegistration:
    thing_name: str
    rig_name: str
    ble_device_id: str | None = None
    version: int | None = None


def normalize_registry_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


class AwsThingRegistryClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def list_rig_things(self, rig_name: str) -> list[ThingRegistration]:
        query = f"attributes.rig:{rig_name}"
        next_token: str | None = None
        thing_names: list[str] = []
        while True:
            request: dict[str, Any] = {
                "indexName": "AWS_Things",
                "queryString": query,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._client.search_index(**request)
            for item in response.get("things", []):
                thing_name = normalize_registry_text(item.get("thingName"))
                if thing_name:
                    thing_names.append(thing_name)
            next_token = normalize_registry_text(response.get("nextToken"))
            if not next_token:
                break

        registrations: list[ThingRegistration] = []
        for thing_name in sorted(set(thing_names)):
            registrations.append(self.describe_thing(thing_name))
        return registrations

    def describe_thing(self, thing_name: str) -> ThingRegistration:
        response = self._client.describe_thing(thingName=thing_name)
        attributes = response.get("attributes") or {}
        rig_name = normalize_registry_text(attributes.get("rig"))
        if rig_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'rig'"
            )
        return ThingRegistration(
            thing_name=thing_name,
            rig_name=rig_name,
            ble_device_id=normalize_registry_text(attributes.get("bleDeviceId")),
            version=response.get("version"),
        )

    def update_registration(
        self,
        thing_name: str,
        *,
        rig_name: str,
        ble_device_id: str | None,
        expected_version: int | None = None,
    ) -> ThingRegistration:
        attributes: dict[str, str] = {"rig": rig_name}
        if ble_device_id is not None:
            attributes["bleDeviceId"] = ble_device_id

        request: dict[str, Any] = {
            "thingName": thing_name,
            "attributePayload": {
                "attributes": attributes,
                "merge": True,
            },
        }
        if expected_version is not None:
            request["expectedVersion"] = expected_version
        self._client.update_thing(**request)
        return self.describe_thing(thing_name)
