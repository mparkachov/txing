from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from aws.thing_capabilities import (
    CAPABILITIES_ATTRIBUTE,
    parse_capabilities_set,
)

LOGGER = logging.getLogger("unit_rig.thing_registry")


class ThingGroupNotFoundError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ThingRegistration:
    thing_name: str
    thing_type: str
    name: str
    short_id: str
    town_name: str
    rig_name: str
    capabilities_set: tuple[str, ...]
    town_id: str | None = None
    rig_id: str | None = None
    version: int | None = None

    @property
    def device_id(self) -> str:
        return self.thing_name


def normalize_registry_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


class AwsThingRegistryClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _list_thing_names_in_group(self, thing_group_name: str) -> list[str]:
        try:
            self._client.describe_thing_group(thingGroupName=thing_group_name)
        except Exception as exc:
            error_code = (
                getattr(exc, "response", {})
                .get("Error", {})
                .get("Code")
            )
            if error_code in {"ResourceNotFoundException", "ResourceNotFound"}:
                raise ThingGroupNotFoundError(
                    f"Dynamic thing group {thing_group_name!r} was not found"
                ) from exc
            raise

        next_token: str | None = None
        thing_names: list[str] = []
        while True:
            request: dict[str, Any] = {
                "thingGroupName": thing_group_name,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._client.list_things_in_thing_group(**request)
            for item in response.get("things", []):
                thing_name = normalize_registry_text(item)
                if thing_name:
                    thing_names.append(thing_name)
            next_token = normalize_registry_text(response.get("nextToken"))
            if not next_token:
                break
        return sorted(set(thing_names))

    def list_rig_things(self, rig_id: str) -> list[ThingRegistration]:
        thing_names = self._list_thing_names_in_group(rig_id)

        registrations: list[ThingRegistration] = []
        for thing_name in thing_names:
            try:
                registration = self.describe_thing(thing_name)
            except RuntimeError as exc:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s: %s",
                    thing_name,
                    rig_id,
                    exc,
                )
                continue
            if registration.rig_id != rig_id:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s because attributes.rigId=%s",
                    thing_name,
                    rig_id,
                    registration.rig_id,
                )
                continue
            registrations.append(registration)
        return registrations

    def describe_rig(self, rig_id: str) -> ThingRegistration:
        registration = self.describe_thing(rig_id)
        if registration.thing_type != "rig":
            raise RuntimeError(f"Thing {rig_id!r} is not a rig")
        return registration

    def describe_thing(self, thing_name: str) -> ThingRegistration:
        response = self._client.describe_thing(thingName=thing_name)
        attributes = response.get("attributes") or {}
        town_id = normalize_registry_text(attributes.get("townId"))
        rig_id = normalize_registry_text(attributes.get("rigId"))
        thing_type = normalize_registry_text(response.get("thingTypeName"))
        name = normalize_registry_text(attributes.get("name"))
        short_id = normalize_registry_text(attributes.get("shortId"))
        if thing_type is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT thing type"
            )
        if name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'name'"
            )
        if short_id is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'shortId'"
            )
        try:
            capabilities_set = parse_capabilities_set(
                attributes.get(CAPABILITIES_ATTRIBUTE),
                thing_name=thing_name,
            )
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc
        if thing_type == "rig":
            if town_id is None:
                raise RuntimeError(
                    f"Thing {thing_name!r} is missing required IoT registry attribute 'townId'"
                )
            rig_id = thing_name
            rig_name = name
            town_name = town_id
        else:
            if town_id is None:
                raise RuntimeError(
                    f"Thing {thing_name!r} is missing required IoT registry attribute 'townId'"
                )
            if rig_id is None:
                raise RuntimeError(
                    f"Thing {thing_name!r} is missing required IoT registry attribute 'rigId'"
                )
            town_name = town_id
            rig_name = rig_id
        return ThingRegistration(
            thing_name=thing_name,
            thing_type=thing_type,
            name=name,
            short_id=short_id,
            town_name=town_name,
            rig_name=rig_name,
            capabilities_set=capabilities_set,
            town_id=town_id,
            rig_id=rig_id,
            version=response.get("version"),
        )

    def assign_device(
        self,
        device_id: str,
        *,
        town_id: str,
        rig_id: str,
        expected_version: int | None = None,
    ) -> ThingRegistration:
        request: dict[str, Any] = {
            "thingName": device_id,
            "attributePayload": {
                "attributes": {
                    "townId": town_id,
                    "rigId": rig_id,
                },
                "merge": True,
            },
        }
        if expected_version is not None:
            request["expectedVersion"] = expected_version
        self._client.update_thing(**request)
        return self.describe_thing(device_id)

DeviceRegistration = ThingRegistration
