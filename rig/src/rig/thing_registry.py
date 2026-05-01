from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from aws.thing_capabilities import (
    CAPABILITIES_ATTRIBUTE,
    parse_capabilities_set,
)

LOGGER = logging.getLogger("rig.thing_registry")


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

    def list_rig_things(self, rig_name: str) -> list[ThingRegistration]:
        thing_names = self._list_thing_names_in_group(rig_name)

        registrations: list[ThingRegistration] = []
        for thing_name in thing_names:
            try:
                registration = self.describe_thing(thing_name)
            except RuntimeError as exc:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s: %s",
                    thing_name,
                    rig_name,
                    exc,
                )
                continue
            if registration.rig_name != rig_name:
                LOGGER.warning(
                    "Skipping thing=%s from dynamic group=%s because attributes.rig=%s",
                    thing_name,
                    rig_name,
                    registration.rig_name,
                )
                continue
            registrations.append(registration)
        return registrations

    def describe_rig_in_town(
        self,
        *,
        town_name: str,
        rig_name: str,
    ) -> ThingRegistration:
        thing_names = self._list_thing_names_in_group(town_name)
        for thing_name in thing_names:
            response = self._client.describe_thing(thingName=thing_name)
            if normalize_registry_text(response.get("thingTypeName")) != "rig":
                continue
            attributes = response.get("attributes") or {}
            if not isinstance(attributes, dict):
                continue
            if normalize_registry_text(attributes.get("town")) != town_name:
                continue
            name = normalize_registry_text(attributes.get("name"))
            short_id = normalize_registry_text(attributes.get("shortId"))
            if name != rig_name:
                continue
            if short_id is None:
                raise RuntimeError(
                    f"Rig thing {thing_name!r} is missing required IoT registry attribute 'shortId'"
                )
            return ThingRegistration(
                thing_name=thing_name,
                thing_type="rig",
                name=name,
                short_id=short_id,
                town_name=town_name,
                rig_name=rig_name,
                capabilities_set=parse_capabilities_set(
                    attributes.get(CAPABILITIES_ATTRIBUTE),
                    thing_name=thing_name,
                ),
                version=response.get("version"),
            )
        raise RuntimeError(
            f"Rig thing for town={town_name!r} rig={rig_name!r} was not found"
        )

    def describe_thing(self, thing_name: str) -> ThingRegistration:
        response = self._client.describe_thing(thingName=thing_name)
        attributes = response.get("attributes") or {}
        town_name = normalize_registry_text(attributes.get("town"))
        rig_name = normalize_registry_text(attributes.get("rig"))
        thing_type = normalize_registry_text(response.get("thingTypeName"))
        name = normalize_registry_text(attributes.get("name"))
        short_id = normalize_registry_text(attributes.get("shortId"))
        if town_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'town'"
            )
        if rig_name is None:
            raise RuntimeError(
                f"Thing {thing_name!r} is missing required IoT registry attribute 'rig'"
            )
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
        return ThingRegistration(
            thing_name=thing_name,
            thing_type=thing_type,
            name=name,
            short_id=short_id,
            town_name=town_name,
            rig_name=rig_name,
            capabilities_set=capabilities_set,
            version=response.get("version"),
        )

    def assign_device(
        self,
        device_id: str,
        *,
        town_name: str,
        rig_name: str,
        expected_version: int | None = None,
    ) -> ThingRegistration:
        request: dict[str, Any] = {
            "thingName": device_id,
            "attributePayload": {
                "attributes": {
                    "town": town_name,
                    "rig": rig_name,
                },
                "merge": True,
            },
        }
        if expected_version is not None:
            request["expectedVersion"] = expected_version
        self._client.update_thing(**request)
        return self.describe_thing(device_id)

DeviceRegistration = ThingRegistration
