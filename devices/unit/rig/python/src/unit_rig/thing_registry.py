from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from aws.thing_capabilities import encode_capabilities_set, parse_capabilities_set
from aws.type_catalog import SsmTypeCatalog, TypeCatalogError, device_type_path, rig_type_path, town_type_path

LOGGER = logging.getLogger("unit_rig.thing_registry")
THING_INDEX_NAME = "AWS_Things"


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
    def __init__(self, client: Any, *, type_catalog: SsmTypeCatalog) -> None:
        self._client = client
        self._type_catalog = type_catalog

    def _record_capabilities(self, path: str, record: dict[str, Any]) -> tuple[str, ...]:
        capabilities = record.get("capabilities")
        if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
            raise RuntimeError(f"SSM type catalog record {path!r} is missing capabilities")
        return parse_capabilities_set(
            encode_capabilities_set(capabilities),
            thing_name=f"type catalog {path}",
        )

    def _is_rig_type(self, thing_type: str) -> bool:
        try:
            self._type_catalog.get_rig_type(thing_type)
        except TypeCatalogError:
            return False
        return True

    def _capabilities_for_town(self) -> tuple[str, ...]:
        path = town_type_path()
        return self._record_capabilities(path, self._type_catalog.get_record(path))

    def _capabilities_for_rig_type(self, rig_type: str) -> tuple[str, ...]:
        path = rig_type_path(rig_type)
        return self._record_capabilities(path, self._type_catalog.get_rig_type(rig_type))

    def _capabilities_for_device_type(self, *, rig_type: str, device_type: str) -> tuple[str, ...]:
        path = device_type_path(rig_type, device_type)
        return self._record_capabilities(
            path,
            self._type_catalog.get_device_type(rig_type, device_type),
        )

    def _search_index_thing_names(self, query_string: str) -> list[str]:
        next_token: str | None = None
        thing_names: list[str] = []
        while True:
            request: dict[str, Any] = {
                "indexName": THING_INDEX_NAME,
                "queryString": query_string,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._client.search_index(**request)
            for thing in response.get("things", []):
                if not isinstance(thing, dict):
                    continue
                thing_name = normalize_registry_text(thing.get("thingName"))
                if thing_name:
                    thing_names.append(thing_name)
            next_token = normalize_registry_text(response.get("nextToken"))
            if not next_token:
                break
        return sorted(set(thing_names))

    def list_rig_things(self, rig_id: str) -> list[ThingRegistration]:
        thing_names = self._search_index_thing_names(
            f"attributes.rigId:{rig_id} AND attributes.townId:*"
        )

        registrations: list[ThingRegistration] = []
        for thing_name in thing_names:
            try:
                registration = self.describe_thing(thing_name)
            except RuntimeError as exc:
                LOGGER.warning(
                    "Skipping thing=%s from fleet index rig=%s: %s",
                    thing_name,
                    rig_id,
                    exc,
                )
                continue
            if registration.rig_id != rig_id:
                LOGGER.warning(
                    "Skipping thing=%s from fleet index rig=%s because attributes.rigId=%s",
                    thing_name,
                    rig_id,
                    registration.rig_id,
                )
                continue
            registrations.append(registration)
        return registrations

    def describe_rig(self, rig_id: str) -> ThingRegistration:
        registration = self.describe_thing(rig_id)
        if not self._is_rig_type(registration.thing_type):
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
        if thing_type == "town":
            capabilities_set = self._capabilities_for_town()
            town_name = name
            rig_name = ""
        elif self._is_rig_type(thing_type):
            if town_id is None:
                raise RuntimeError(
                    f"Thing {thing_name!r} is missing required IoT registry attribute 'townId'"
                )
            rig_id = thing_name
            rig_name = name
            town_name = town_id
            capabilities_set = self._capabilities_for_rig_type(thing_type)
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
            rig_registration = self.describe_thing(rig_id)
            capabilities_set = self._capabilities_for_device_type(
                rig_type=rig_registration.thing_type,
                device_type=thing_type,
            )
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
