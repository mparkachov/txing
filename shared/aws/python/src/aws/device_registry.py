from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import re
from typing import Any

from .auth import AwsRuntime, build_aws_runtime, ensure_aws_profile, resolve_aws_region
from .device_catalog import DeviceManifest, discover_repo_root, load_device_manifest
from .sparkplug_shadow import (
    build_offline_device_shadow_payload,
    build_offline_node_shadow_payload,
    build_static_group_shadow_payload,
)
from .thing_capabilities import (
    CAPABILITIES_ATTRIBUTE,
    encode_capabilities_set,
    parse_capabilities_set,
)
from .type_catalog import (
    SsmTypeCatalog,
    TypeCatalogError,
    device_type_path,
    town_type_path,
)


THING_INDEX_NAME = "AWS_Things"
SHORT_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
SHORT_ID_LENGTH = 6
RESOURCE_NOT_FOUND_CODES = {
    "NotFoundException",
    "ResourceNotFound",
    "ResourceNotFoundException",
}
DEVICE_TYPE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOWN_THING_TYPE = "town"
RIG_THING_TYPE = "rig"
TOWN_ID_ATTRIBUTE = "townId"
RIG_ID_ATTRIBUTE = "rigId"
RIG_TYPE_ATTRIBUTE = "rigType"
DEVICE_TYPE_ATTRIBUTE = "deviceType"
TOWN_THING_SEARCHABLE_ATTRIBUTES = ("name",)
RIG_THING_SEARCHABLE_ATTRIBUTES = ("name", TOWN_ID_ATTRIBUTE, RIG_TYPE_ATTRIBUTE)
DEVICE_THING_SEARCHABLE_ATTRIBUTES = (
    "name",
    TOWN_ID_ATTRIBUTE,
    RIG_ID_ATTRIBUTE,
    DEVICE_TYPE_ATTRIBUTE,
)


class DeviceRegistryError(RuntimeError):
    pass


def normalize_registry_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _is_resource_not_found(err: Exception) -> bool:
    return (
        getattr(err, "response", {})
        .get("Error", {})
        .get("Code")
        in RESOURCE_NOT_FOUND_CODES
    )


def _require_registry_attribute(
    attributes: dict[str, Any],
    key: str,
    *,
    thing_name: str,
) -> str:
    value = normalize_registry_text(attributes.get(key))
    if value is None:
        raise DeviceRegistryError(
            f"Thing {thing_name!r} is missing required IoT registry attribute {key!r}"
        )
    return value


def _normalize_slug(label: str, value: str) -> str:
    text = value.strip().lower()
    if not text:
        raise DeviceRegistryError(f"{label} must be non-empty")
    if not DEVICE_TYPE_PATTERN.fullmatch(text):
        raise DeviceRegistryError(
            f"{label} must match {DEVICE_TYPE_PATTERN.pattern!r}; got {value!r}"
        )
    return text


def _generate_short_id(rng: random.Random) -> str:
    return "".join(rng.choice(SHORT_ID_ALPHABET) for _ in range(SHORT_ID_LENGTH))


def build_thing_name(thing_type: str, short_id: str) -> str:
    return f"{thing_type}-{short_id}"


def build_device_id(device_type: str, short_id: str) -> str:
    return build_thing_name(device_type, short_id)


def build_town_group_query(town_id: str) -> str:
    normalized_town_id = _normalize_slug("town id", town_id)
    return f"thingTypeName:{RIG_THING_TYPE} AND attributes.{TOWN_ID_ATTRIBUTE}:{normalized_town_id}"


def build_rig_group_query(rig_id: str) -> str:
    normalized_rig_id = _normalize_slug("rig id", rig_id)
    return f"attributes.{RIG_ID_ATTRIBUTE}:{normalized_rig_id} AND attributes.{TOWN_ID_ATTRIBUTE}:*"


def _record_capabilities(record: dict[str, Any], *, path: str) -> tuple[str, ...]:
    capabilities = record.get("capabilities")
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise DeviceRegistryError(f"SSM type catalog record {path!r} is missing capabilities")
    return parse_capabilities_set(
        encode_capabilities_set(capabilities),
        thing_name=f"type catalog {path}",
    )


def _record_searchable_attributes(
    record: dict[str, Any],
    *,
    path: str,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    attributes = record.get("searchableAttributes")
    if attributes is None:
        return fallback
    if not isinstance(attributes, list) or any(not isinstance(item, str) or not item for item in attributes):
        raise DeviceRegistryError(f"SSM type catalog record {path!r} has invalid searchableAttributes")
    return tuple(attributes)


@dataclass(slots=True, frozen=True)
class ThingRegistration:
    thing_name: str
    thing_type: str
    name: str
    short_id: str
    capabilities: tuple[str, ...]
    town_id: str | None = None
    rig_id: str | None = None
    rig_type: str | None = None
    device_type: str | None = None
    version: int | None = None

    @property
    def device_id(self) -> str:
        return self.thing_name


DeviceRegistration = ThingRegistration


class AwsDeviceRegistry:
    def __init__(
        self,
        runtime: AwsRuntime,
        *,
        repo_root: Path | None = None,
        random_source: random.Random | None = None,
        type_catalog: SsmTypeCatalog | None = None,
    ) -> None:
        self._runtime = runtime
        self._repo_root = discover_repo_root(repo_root)
        self._rng = random_source or random.SystemRandom()
        self._iot_client = runtime.iot_client()
        self._iot_data_client: Any | None = None
        self._type_catalog = type_catalog or SsmTypeCatalog(
            runtime.client("ssm"),
            repo_root=self._repo_root,
        )

    def _iot_data(self) -> Any:
        if self._iot_data_client is None:
            self._iot_data_client = self._runtime.client(
                "iot-data",
                endpoint_url=f"https://{self._runtime.iot_data_endpoint()}",
            )
        return self._iot_data_client

    def describe_thing(self, thing_name: str) -> ThingRegistration:
        return self._describe_thing(thing_name)

    def _describe_thing(self, thing_name: str) -> ThingRegistration:
        response = self._iot_client.describe_thing(thingName=thing_name)
        attributes = response.get("attributes") or {}
        if not isinstance(attributes, dict):
            raise DeviceRegistryError(
                f"Thing {thing_name!r} returned invalid IoT registry attributes"
            )
        thing_type = _require_registry_attribute(
            {"thingTypeName": response.get("thingTypeName")},
            "thingTypeName",
            thing_name=thing_name,
        )
        name = _require_registry_attribute(attributes, "name", thing_name=thing_name)
        short_id = _require_registry_attribute(attributes, "shortId", thing_name=thing_name)
        capabilities = parse_capabilities_set(
            attributes.get(CAPABILITIES_ATTRIBUTE),
            thing_name=thing_name,
        )
        town_id: str | None = None
        rig_id: str | None = None
        rig_type: str | None = None
        device_type: str | None = None
        if thing_type == RIG_THING_TYPE:
            town_id = _require_registry_attribute(attributes, TOWN_ID_ATTRIBUTE, thing_name=thing_name)
            rig_type = _require_registry_attribute(attributes, RIG_TYPE_ATTRIBUTE, thing_name=thing_name)
        elif thing_type != TOWN_THING_TYPE:
            town_id = _require_registry_attribute(attributes, TOWN_ID_ATTRIBUTE, thing_name=thing_name)
            rig_id = _require_registry_attribute(attributes, RIG_ID_ATTRIBUTE, thing_name=thing_name)
            device_type = _require_registry_attribute(attributes, DEVICE_TYPE_ATTRIBUTE, thing_name=thing_name)
            if device_type != thing_type:
                raise DeviceRegistryError(
                    f"Thing {thing_name!r} deviceType={device_type!r} does not match thing type {thing_type!r}"
                )
        return ThingRegistration(
            thing_name=thing_name,
            thing_type=thing_type,
            name=name,
            short_id=short_id,
            capabilities=capabilities,
            town_id=town_id,
            rig_id=rig_id,
            rig_type=rig_type,
            device_type=device_type,
            version=response.get("version"),
        )

    def describe_device(self, device_id: str) -> DeviceRegistration:
        return self.describe_thing(device_id)

    def _thing_exists(self, thing_name: str) -> bool:
        try:
            self._iot_client.describe_thing(thingName=thing_name)
        except Exception as err:
            if _is_resource_not_found(err):
                return False
            raise
        return True

    def _allocate_thing_name(self, thing_type: str) -> tuple[str, str]:
        normalized_thing_type = _normalize_slug("thing type", thing_type)
        for _ in range(256):
            short_id = _generate_short_id(self._rng)
            thing_name = build_thing_name(normalized_thing_type, short_id)
            if not self._thing_exists(thing_name):
                return thing_name, short_id
        raise DeviceRegistryError(
            f"failed to allocate unique thing name for type {normalized_thing_type!r}"
        )

    def _search_index(self, query_string: str) -> list[ThingRegistration]:
        next_token: str | None = None
        thing_names: list[str] = []
        while True:
            request: dict[str, Any] = {
                "indexName": THING_INDEX_NAME,
                "queryString": query_string,
                "maxResults": 100,
            }
            if next_token is not None:
                request["nextToken"] = next_token
            response = self._iot_client.search_index(**request)
            for thing in response.get("things", []):
                if not isinstance(thing, dict):
                    continue
                thing_name = normalize_registry_text(thing.get("thingName"))
                if thing_name is not None:
                    thing_names.append(thing_name)
            next_token = normalize_registry_text(response.get("nextToken"))
            if next_token is None:
                break
        return [self._describe_thing(thing_name) for thing_name in sorted(set(thing_names))]

    def _list_registry_things(self) -> list[ThingRegistration]:
        next_token: str | None = None
        registrations: list[ThingRegistration] = []
        while True:
            request: dict[str, Any] = {"maxResults": 100}
            if next_token is not None:
                request["nextToken"] = next_token
            response = self._iot_client.list_things(**request)
            for thing in response.get("things", []):
                if not isinstance(thing, dict):
                    continue
                thing_name = normalize_registry_text(thing.get("thingName"))
                if thing_name is None:
                    continue
                registrations.append(self._describe_thing(thing_name))
            next_token = normalize_registry_text(response.get("nextToken"))
            if next_token is None:
                break
        return registrations

    def _find_things_in_registry(
        self,
        *,
        thing_type: str,
        name: str,
        town_id: str | None = None,
        rig_id: str | None = None,
        rig_type: str | None = None,
    ) -> list[ThingRegistration]:
        normalized_name = _normalize_slug("name", name)
        normalized_town_id = _normalize_slug("town id", town_id) if town_id is not None else None
        normalized_rig_id = _normalize_slug("rig id", rig_id) if rig_id is not None else None
        normalized_rig_type = _normalize_slug("rig type", rig_type) if rig_type is not None else None
        matches: list[ThingRegistration] = []
        for registration in self._list_registry_things():
            if registration.thing_type != thing_type:
                continue
            if registration.name != normalized_name:
                continue
            if normalized_town_id is not None and registration.town_id != normalized_town_id:
                continue
            if normalized_rig_id is not None and registration.rig_id != normalized_rig_id:
                continue
            if normalized_rig_type is not None and registration.rig_type != normalized_rig_type:
                continue
            matches.append(registration)
        return matches

    def describe_town_by_name(self, town_name: str) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        matches = self._search_index(
            f"thingTypeName:{TOWN_THING_TYPE} AND attributes.name:{normalized_town_name}"
        )
        if not matches:
            matches = self._find_things_in_registry(
                thing_type=TOWN_THING_TYPE,
                name=normalized_town_name,
            )
        if not matches:
            raise DeviceRegistryError(
                f"Town {normalized_town_name!r} is not registered in AWS IoT"
            )
        if len(matches) > 1:
            raise DeviceRegistryError(
                f"Town {normalized_town_name!r} matched multiple AWS IoT things"
            )
        return matches[0]

    def describe_rig_by_name(
        self,
        *,
        town_id: str,
        rig_name: str,
        rig_type: str | None = None,
    ) -> ThingRegistration:
        normalized_town_id = _normalize_slug("town id", town_id)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        normalized_rig_type = _normalize_slug("rig type", rig_type) if rig_type else None
        query = (
            f"thingTypeName:{RIG_THING_TYPE} AND attributes.name:{normalized_rig_name} "
            f"AND attributes.{TOWN_ID_ATTRIBUTE}:{normalized_town_id}"
        )
        if normalized_rig_type is not None:
            query += f" AND attributes.{RIG_TYPE_ATTRIBUTE}:{normalized_rig_type}"
        matches = self._search_index(query)
        if not matches:
            matches = self._find_things_in_registry(
                thing_type=RIG_THING_TYPE,
                name=normalized_rig_name,
                town_id=normalized_town_id,
                rig_type=normalized_rig_type,
            )
        if not matches:
            raise DeviceRegistryError(
                f"Rig {normalized_rig_name!r} in town id {normalized_town_id!r} is not registered in AWS IoT"
            )
        if len(matches) > 1:
            raise DeviceRegistryError(
                f"Rig {normalized_rig_name!r} in town id {normalized_town_id!r} matched multiple AWS IoT things"
            )
        return matches[0]

    def describe_device_by_name(
        self,
        *,
        rig_id: str,
        device_type: str,
        device_name: str,
    ) -> DeviceRegistration:
        normalized_rig_id = _normalize_slug("rig id", rig_id)
        normalized_device_type = _normalize_slug("device type", device_type)
        normalized_device_name = _normalize_slug("device", device_name)
        matches = self._search_index(
            f"thingTypeName:{normalized_device_type} AND attributes.name:{normalized_device_name} "
            f"AND attributes.{RIG_ID_ATTRIBUTE}:{normalized_rig_id} "
            f"AND attributes.{DEVICE_TYPE_ATTRIBUTE}:{normalized_device_type}"
        )
        if not matches:
            matches = self._find_things_in_registry(
                thing_type=normalized_device_type,
                name=normalized_device_name,
                rig_id=normalized_rig_id,
            )
        if not matches:
            raise DeviceRegistryError(
                "Device "
                f"{normalized_device_name!r} of type {normalized_device_type!r} "
                f"under rig id {normalized_rig_id!r} is not registered in AWS IoT"
            )
        if len(matches) > 1:
            raise DeviceRegistryError(
                "Device "
                f"{normalized_device_name!r} of type {normalized_device_type!r} "
                f"under rig id {normalized_rig_id!r} matched multiple AWS IoT things"
            )
        return matches[0]

    def ensure_town_group(self, town_id: str) -> None:
        normalized_town_id = _normalize_slug("town id", town_id)
        properties = {
            "thingGroupDescription": f"Dynamic rig membership for town id {normalized_town_id}",
            "attributePayload": {
                "attributes": {TOWN_ID_ATTRIBUTE: normalized_town_id},
                "merge": True,
            },
        }
        query_string = build_town_group_query(normalized_town_id)
        try:
            self._iot_client.describe_thing_group(thingGroupName=normalized_town_id)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_client.create_dynamic_thing_group(
                thingGroupName=normalized_town_id,
                thingGroupProperties=properties,
                indexName=THING_INDEX_NAME,
                queryString=query_string,
            )
            return
        self._iot_client.update_dynamic_thing_group(
            thingGroupName=normalized_town_id,
            thingGroupProperties=properties,
            indexName=THING_INDEX_NAME,
            queryString=query_string,
        )

    def ensure_rig_group(self, rig_id: str) -> None:
        normalized_rig_id = _normalize_slug("rig id", rig_id)
        properties = {
            "thingGroupDescription": f"Dynamic device membership for rig id {normalized_rig_id}",
            "attributePayload": {
                "attributes": {RIG_ID_ATTRIBUTE: normalized_rig_id},
                "merge": True,
            },
        }
        query_string = build_rig_group_query(normalized_rig_id)
        try:
            self._iot_client.describe_thing_group(thingGroupName=normalized_rig_id)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_client.create_dynamic_thing_group(
                thingGroupName=normalized_rig_id,
                thingGroupProperties=properties,
                indexName=THING_INDEX_NAME,
                queryString=query_string,
            )
            return

        self._iot_client.update_dynamic_thing_group(
            thingGroupName=normalized_rig_id,
            thingGroupProperties=properties,
            indexName=THING_INDEX_NAME,
            queryString=query_string,
        )

    def ensure_thing_type(
        self,
        thing_type: str,
        *,
        searchable_attributes: tuple[str, ...],
        description: str,
    ) -> None:
        normalized_thing_type = _normalize_slug("thing type", thing_type)
        expected_searchable_attributes = list(searchable_attributes)
        try:
            response = self._iot_client.describe_thing_type(
                thingTypeName=normalized_thing_type
            )
            current_properties = response.get("thingTypeProperties") or {}
            current_searchable_attributes = current_properties.get("searchableAttributes") or []
            if not isinstance(current_searchable_attributes, list):
                current_searchable_attributes = []
            current_attribute_set = {
                attribute
                for attribute in current_searchable_attributes
                if isinstance(attribute, str) and attribute
            }
            missing_attributes = [
                attribute
                for attribute in expected_searchable_attributes
                if attribute not in current_attribute_set
            ]
            if missing_attributes:
                missing_text = ", ".join(sorted(missing_attributes))
                raise DeviceRegistryError(
                    "Thing type "
                    f"{normalized_thing_type!r} already exists without required "
                    f"searchableAttributes ({missing_text}). "
                    "AWS IoT thing types are immutable; delete and recreate the thing type "
                    "before registering things again."
                )
            return
        except Exception as err:
            if isinstance(err, DeviceRegistryError):
                raise
            if not _is_resource_not_found(err):
                raise
        self._iot_client.create_thing_type(
            thingTypeName=normalized_thing_type,
            thingTypeProperties={
                "thingTypeDescription": description,
                "searchableAttributes": expected_searchable_attributes,
            },
        )

    def ensure_shadow_initialized(
        self,
        thing_name: str,
        *,
        payload: bytes,
        shadow_name: str | None = None,
    ) -> bool:
        kwargs = {"thingName": thing_name}
        if shadow_name is not None:
            kwargs["shadowName"] = shadow_name
        try:
            self._iot_data().get_thing_shadow(**kwargs)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_data().update_thing_shadow(**kwargs, payload=payload)
            return True
        return False

    def ensure_device_shadow_initialized(
        self,
        thing_name: str,
        *,
        manifest: DeviceManifest,
        capabilities: tuple[str, ...],
        town_name: str,
        rig_name: str,
    ) -> bool:
        initialized = False
        for shadow_name in capabilities:
            if shadow_name == "sparkplug":
                payload = json.dumps(
                    build_offline_device_shadow_payload(
                        group_id=town_name,
                        edge_node_id=rig_name,
                        device_id=thing_name,
                    ),
                    sort_keys=True,
                ).encode("utf-8")
            else:
                payload = manifest.load_default_shadow_bytes(shadow_name)
            initialized = (
                self.ensure_shadow_initialized(
                    thing_name,
                    shadow_name=shadow_name,
                    payload=payload,
                )
                or initialized
            )
        return initialized

    def ensure_town_shadow_initialized(self, thing_name: str, *, town_name: str) -> bool:
        payload = json.dumps(
            build_static_group_shadow_payload(town_name),
            sort_keys=True,
        ).encode("utf-8")
        return self.ensure_shadow_initialized(
            thing_name,
            shadow_name="sparkplug",
            payload=payload,
        )

    def ensure_rig_shadow_initialized(
        self,
        thing_name: str,
        *,
        town_name: str,
        rig_name: str,
    ) -> bool:
        payload = json.dumps(
            build_offline_node_shadow_payload(
                group_id=town_name,
                edge_node_id=rig_name,
            ),
            sort_keys=True,
        ).encode("utf-8")
        return self.ensure_shadow_initialized(
            thing_name,
            shadow_name="sparkplug",
            payload=payload,
        )

    def ensure_rig_attributes(
        self,
        registration: ThingRegistration,
        *,
        town_id: str,
        rig_name: str,
        rig_type: str,
        capabilities: tuple[str, ...],
    ) -> None:
        request: dict[str, Any] = {
            "thingName": registration.thing_name,
            "attributePayload": {
                "attributes": {
                    "name": rig_name,
                    TOWN_ID_ATTRIBUTE: town_id,
                    RIG_TYPE_ATTRIBUTE: rig_type,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                },
                "merge": True,
            },
        }
        if registration.version is not None:
            request["expectedVersion"] = registration.version
        self._iot_client.update_thing(**request)

    def ensure_device_attributes(
        self,
        registration: ThingRegistration,
        *,
        town_id: str,
        rig_id: str,
        device_type: str,
        device_name: str,
        capabilities: tuple[str, ...],
    ) -> None:
        request: dict[str, Any] = {
            "thingName": registration.thing_name,
            "attributePayload": {
                "attributes": {
                    "name": device_name,
                    "shortId": registration.short_id,
                    TOWN_ID_ATTRIBUTE: town_id,
                    RIG_ID_ATTRIBUTE: rig_id,
                    DEVICE_TYPE_ATTRIBUTE: device_type,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                },
                "merge": True,
            },
        }
        if registration.version is not None:
            request["expectedVersion"] = registration.version
        self._iot_client.update_thing(**request)

    def ensure_auxiliary_resources(self, thing_name: str, *, manifest: DeviceManifest) -> None:
        channel_name = manifest.render_board_video_channel_name(device_id=thing_name)
        if channel_name:
            self.ensure_signaling_channel(channel_name)

    def ensure_signaling_channel(self, channel_name: str) -> None:
        client = self._runtime.client("kinesisvideo", region_name=self._runtime.region_name)
        try:
            client.describe_signaling_channel(ChannelName=channel_name)
            return
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
        client.create_signaling_channel(
            ChannelName=channel_name,
            ChannelType="SINGLE_MASTER",
            SingleMasterConfiguration={"MessageTtlSeconds": 60},
        )

    def register_town(self, *, town_name: str) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        path = town_type_path()
        capabilities = _record_capabilities(self._type_catalog.get_record(path), path=path)
        self.ensure_thing_type(
            TOWN_THING_TYPE,
            searchable_attributes=TOWN_THING_SEARCHABLE_ATTRIBUTES,
            description="Registered txing town type",
        )
        thing_name, short_id = self._allocate_thing_name(TOWN_THING_TYPE)
        self._iot_client.create_thing(
            thingName=thing_name,
            thingTypeName=TOWN_THING_TYPE,
            attributePayload={
                "attributes": {
                    "name": normalized_town_name,
                    "shortId": short_id,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                }
            },
        )
        self.ensure_town_group(thing_name)
        self.ensure_town_shadow_initialized(thing_name, town_name=normalized_town_name)
        return self.describe_thing(thing_name)

    def ensure_town(self, *, town_name: str) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        try:
            registration = self.describe_town_by_name(normalized_town_name)
        except DeviceRegistryError as err:
            if "is not registered" not in str(err):
                raise
            return self.register_town(town_name=normalized_town_name)
        self.ensure_thing_type(
            TOWN_THING_TYPE,
            searchable_attributes=TOWN_THING_SEARCHABLE_ATTRIBUTES,
            description="Registered txing town type",
        )
        self.ensure_town_group(registration.thing_name)
        self.ensure_town_shadow_initialized(
            registration.thing_name,
            town_name=normalized_town_name,
        )
        return self.describe_thing(registration.thing_name)

    def register_rig(
        self,
        *,
        town_id: str,
        rig_type: str,
        rig_name: str,
    ) -> ThingRegistration:
        normalized_town_id = _normalize_slug("town id", town_id)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        normalized_rig_type = _normalize_slug("rig type", rig_type)
        town_registration = self.describe_thing(normalized_town_id)
        if town_registration.thing_type != TOWN_THING_TYPE:
            raise DeviceRegistryError(f"Thing {normalized_town_id!r} is not a town")
        path = f"/txing/town/{normalized_rig_type}"
        record = self._type_catalog.get_rig_type(normalized_rig_type)
        capabilities = _record_capabilities(record, path=path)
        searchable_attributes = _record_searchable_attributes(
            record,
            path=path,
            fallback=RIG_THING_SEARCHABLE_ATTRIBUTES,
        )
        self.ensure_thing_type(
            RIG_THING_TYPE,
            searchable_attributes=searchable_attributes,
            description="Registered txing rig thing type",
        )
        thing_name, short_id = self._allocate_thing_name(RIG_THING_TYPE)
        self._iot_client.create_thing(
            thingName=thing_name,
            thingTypeName=RIG_THING_TYPE,
            attributePayload={
                "attributes": {
                    "name": normalized_rig_name,
                    "shortId": short_id,
                    TOWN_ID_ATTRIBUTE: town_registration.thing_name,
                    RIG_TYPE_ATTRIBUTE: normalized_rig_type,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                }
            },
        )
        self.ensure_town_group(town_registration.thing_name)
        self.ensure_rig_group(thing_name)
        self.ensure_rig_shadow_initialized(
            thing_name,
            town_name=town_registration.name,
            rig_name=normalized_rig_name,
        )
        return self.describe_thing(thing_name)

    def ensure_rig(
        self,
        *,
        town_id: str,
        rig_type: str,
        rig_name: str,
    ) -> ThingRegistration:
        normalized_town_id = _normalize_slug("town id", town_id)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        normalized_rig_type = _normalize_slug("rig type", rig_type)
        town_registration = self.describe_thing(normalized_town_id)
        if town_registration.thing_type != TOWN_THING_TYPE:
            raise DeviceRegistryError(f"Thing {normalized_town_id!r} is not a town")
        path = f"/txing/town/{normalized_rig_type}"
        record = self._type_catalog.get_rig_type(normalized_rig_type)
        capabilities = _record_capabilities(record, path=path)
        try:
            registration = self.describe_rig_by_name(
                town_id=town_registration.thing_name,
                rig_name=normalized_rig_name,
                rig_type=normalized_rig_type,
            )
        except DeviceRegistryError as err:
            if "is not registered" not in str(err):
                raise
            return self.register_rig(
                town_id=town_registration.thing_name,
                rig_type=normalized_rig_type,
                rig_name=normalized_rig_name,
            )
        searchable_attributes = _record_searchable_attributes(
            record,
            path=path,
            fallback=RIG_THING_SEARCHABLE_ATTRIBUTES,
        )
        self.ensure_thing_type(
            RIG_THING_TYPE,
            searchable_attributes=searchable_attributes,
            description="Registered txing rig thing type",
        )
        self.ensure_town_group(town_registration.thing_name)
        self.ensure_rig_group(registration.thing_name)
        self.ensure_rig_attributes(
            registration,
            town_id=town_registration.thing_name,
            rig_name=normalized_rig_name,
            rig_type=normalized_rig_type,
            capabilities=capabilities,
        )
        self.ensure_rig_shadow_initialized(
            registration.thing_name,
            town_name=town_registration.name,
            rig_name=normalized_rig_name,
        )
        return self.describe_thing(registration.thing_name)

    def _validate_device_compatibility(
        self,
        *,
        device_type: str,
        rig_registration: ThingRegistration,
    ) -> dict[str, Any]:
        if rig_registration.thing_type != RIG_THING_TYPE:
            raise DeviceRegistryError(f"Thing {rig_registration.thing_name!r} is not a rig")
        if rig_registration.rig_type is None:
            raise DeviceRegistryError(
                f"Rig {rig_registration.thing_name!r} is missing required rigType"
            )
        try:
            return self._type_catalog.get_device_type(rig_registration.rig_type, device_type)
        except TypeCatalogError as err:
            path = device_type_path(rig_registration.rig_type, device_type)
            raise DeviceRegistryError(
                f"Device type {device_type!r} is not compatible with rig type "
                f"{rig_registration.rig_type!r}; missing SSM type catalog record {path!r}"
            ) from err

    def register_device(
        self,
        *,
        rig_id: str,
        device_type: str,
        device_name: str | None = None,
    ) -> DeviceRegistration:
        rig_registration = self.describe_thing(_normalize_slug("rig id", rig_id))
        if rig_registration.town_id is None:
            raise DeviceRegistryError(
                f"Rig {rig_registration.thing_name!r} is missing required townId"
            )
        town_registration = self.describe_thing(rig_registration.town_id)
        manifest = load_device_manifest(device_type, repo_root=self._repo_root)
        normalized_device_type = _normalize_slug("device type", manifest.type)
        normalized_device_name = _normalize_slug(
            "device",
            device_name if device_name is not None else manifest.device_name,
        )
        record = self._validate_device_compatibility(
            device_type=normalized_device_type,
            rig_registration=rig_registration,
        )
        path = device_type_path(rig_registration.rig_type or "", normalized_device_type)
        capabilities = _record_capabilities(record, path=path)
        searchable_attributes = _record_searchable_attributes(
            record,
            path=path,
            fallback=DEVICE_THING_SEARCHABLE_ATTRIBUTES,
        )
        thing_name, short_id = self._allocate_thing_name(normalized_device_type)
        self.ensure_thing_type(
            normalized_device_type,
            searchable_attributes=searchable_attributes,
            description=f"Registered txing device type {normalized_device_type}",
        )
        self._iot_client.create_thing(
            thingName=thing_name,
            thingTypeName=normalized_device_type,
            attributePayload={
                "attributes": {
                    "name": normalized_device_name,
                    "shortId": short_id,
                    TOWN_ID_ATTRIBUTE: town_registration.thing_name,
                    RIG_ID_ATTRIBUTE: rig_registration.thing_name,
                    DEVICE_TYPE_ATTRIBUTE: normalized_device_type,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                }
            },
        )
        self.ensure_town_group(town_registration.thing_name)
        self.ensure_rig_group(rig_registration.thing_name)
        self.ensure_device_shadow_initialized(
            thing_name,
            manifest=manifest,
            capabilities=capabilities,
            town_name=town_registration.name,
            rig_name=rig_registration.name,
        )
        self.ensure_auxiliary_resources(thing_name, manifest=manifest)
        return self.describe_device(thing_name)

    def ensure_device(
        self,
        *,
        rig_id: str,
        device_type: str,
        device_name: str,
    ) -> DeviceRegistration:
        rig_registration = self.describe_thing(_normalize_slug("rig id", rig_id))
        if rig_registration.town_id is None:
            raise DeviceRegistryError(
                f"Rig {rig_registration.thing_name!r} is missing required townId"
            )
        town_registration = self.describe_thing(rig_registration.town_id)
        manifest = load_device_manifest(device_type, repo_root=self._repo_root)
        normalized_device_type = _normalize_slug("device type", manifest.type)
        normalized_device_name = _normalize_slug("device", device_name)
        try:
            registration = self.describe_device_by_name(
                rig_id=rig_registration.thing_name,
                device_type=normalized_device_type,
                device_name=normalized_device_name,
            )
        except DeviceRegistryError as err:
            if "is not registered" not in str(err):
                raise
            return self.register_device(
                rig_id=rig_registration.thing_name,
                device_type=normalized_device_type,
                device_name=normalized_device_name,
            )
        record = self._validate_device_compatibility(
            device_type=normalized_device_type,
            rig_registration=rig_registration,
        )
        path = device_type_path(rig_registration.rig_type or "", normalized_device_type)
        capabilities = _record_capabilities(record, path=path)
        searchable_attributes = _record_searchable_attributes(
            record,
            path=path,
            fallback=DEVICE_THING_SEARCHABLE_ATTRIBUTES,
        )
        self.ensure_thing_type(
            normalized_device_type,
            searchable_attributes=searchable_attributes,
            description=f"Registered txing device type {normalized_device_type}",
        )
        self.ensure_town_group(town_registration.thing_name)
        self.ensure_rig_group(rig_registration.thing_name)
        self.ensure_device_attributes(
            registration,
            town_id=town_registration.thing_name,
            rig_id=rig_registration.thing_name,
            device_type=normalized_device_type,
            device_name=normalized_device_name,
            capabilities=capabilities,
        )
        self.ensure_device_shadow_initialized(
            registration.thing_name,
            manifest=manifest,
            capabilities=capabilities,
            town_name=town_registration.name,
            rig_name=rig_registration.name,
        )
        self.ensure_auxiliary_resources(registration.thing_name, manifest=manifest)
        return self.describe_device(registration.thing_name)

    def assign_device(self, device_id: str, *, rig_id: str) -> DeviceRegistration:
        registration = self.describe_device(_normalize_slug("device id", device_id))
        normalized_rig_id = _normalize_slug("rig id", rig_id)
        rig_registration = self.describe_thing(normalized_rig_id)
        if rig_registration.town_id is None:
            raise DeviceRegistryError(
                f"Rig {rig_registration.thing_name!r} is missing required townId"
            )
        device_type = registration.device_type or registration.thing_type
        record = self._validate_device_compatibility(
            device_type=device_type,
            rig_registration=rig_registration,
        )
        path = device_type_path(rig_registration.rig_type or "", device_type)
        capabilities = _record_capabilities(record, path=path)
        self.ensure_town_group(rig_registration.town_id)
        self.ensure_rig_group(rig_registration.thing_name)
        request: dict[str, Any] = {
            "thingName": registration.device_id,
            "attributePayload": {
                "attributes": {
                    TOWN_ID_ATTRIBUTE: rig_registration.town_id,
                    RIG_ID_ATTRIBUTE: rig_registration.thing_name,
                    DEVICE_TYPE_ATTRIBUTE: device_type,
                    CAPABILITIES_ATTRIBUTE: encode_capabilities_set(capabilities),
                },
                "merge": True,
            },
        }
        if registration.version is not None:
            request["expectedVersion"] = registration.version
        self._iot_client.update_thing(**request)
        return self.describe_device(device_id)


def _build_registry(*, region_name: str, repo_root: Path | None) -> AwsDeviceRegistry:
    ensure_aws_profile("AWS_SELECTED_PROFILE", "AWS_TOWN_PROFILE")
    runtime = build_aws_runtime(region_name=region_name)
    return AwsDeviceRegistry(runtime, repo_root=repo_root)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register and assign hierarchical txing things in AWS IoT",
    )
    parser.add_argument(
        "--region",
        default="",
        help="Override AWS region (default: resolve from environment or shared AWS config)",
    )
    parser.add_argument(
        "--repo-root",
        default="",
        help="Override repo root discovery (default: infer from cwd)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_town_parser = subparsers.add_parser(
        "register-town",
        help="Create a new registered town thing and initialize its shadow",
    )
    register_town_parser.add_argument("--town", required=True)

    ensure_town_parser = subparsers.add_parser(
        "ensure-town",
        help="Create or update the configured town thing, group, and shadow",
    )
    ensure_town_parser.add_argument("--town", required=True)

    register_rig_parser = subparsers.add_parser(
        "register-rig",
        help="Create a new registered rig thing and initialize its shadow",
    )
    register_rig_parser.add_argument("--town-id", required=True)
    register_rig_parser.add_argument("--rig-type", required=True)
    register_rig_parser.add_argument("--rig", required=True)

    ensure_rig_parser = subparsers.add_parser(
        "ensure-rig",
        help="Create or update the configured rig thing, group, and shadow",
    )
    ensure_rig_parser.add_argument("--town-id", required=True)
    ensure_rig_parser.add_argument("--rig-type", required=True)
    ensure_rig_parser.add_argument("--rig", required=True)

    register_device_parser = subparsers.add_parser(
        "register-device",
        help="Create a new registered device thing and initialize its type resources",
    )
    register_device_parser.add_argument("--rig-id", required=True)
    register_device_parser.add_argument("--device-type", required=True)
    register_device_parser.add_argument("--device-name", default="")

    ensure_device_parser = subparsers.add_parser(
        "ensure-device",
        help="Create or update the configured device thing, shadows, and KVS resources",
    )
    ensure_device_parser.add_argument("--rig-id", required=True)
    ensure_device_parser.add_argument("--device-type", required=True)
    ensure_device_parser.add_argument("--device-name", required=True)

    assign_parser = subparsers.add_parser(
        "assign-device",
        help="Move an existing registered device to a new rig assignment",
    )
    assign_parser.add_argument("--device-id", required=True)
    assign_parser.add_argument("--rig-id", required=True)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    region_name = args.region.strip() or resolve_aws_region()
    if not region_name:
        raise RuntimeError(
            "AWS region is required; set AWS_REGION/AWS_DEFAULT_REGION or pass --region"
        )

    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    registry = _build_registry(region_name=region_name, repo_root=repo_root)
    if args.command == "register-town":
        registration = registry.register_town(town_name=args.town)
    elif args.command == "ensure-town":
        registration = registry.ensure_town(town_name=args.town)
    elif args.command == "register-rig":
        registration = registry.register_rig(
            town_id=args.town_id,
            rig_type=args.rig_type,
            rig_name=args.rig,
        )
    elif args.command == "ensure-rig":
        registration = registry.ensure_rig(
            town_id=args.town_id,
            rig_type=args.rig_type,
            rig_name=args.rig,
        )
    elif args.command == "register-device":
        registration = registry.register_device(
            rig_id=args.rig_id,
            device_type=args.device_type,
            device_name=args.device_name or None,
        )
    elif args.command == "ensure-device":
        registration = registry.ensure_device(
            rig_id=args.rig_id,
            device_type=args.device_type,
            device_name=args.device_name,
        )
    elif args.command == "assign-device":
        registration = registry.assign_device(
            args.device_id,
            rig_id=args.rig_id,
        )
    else:  # pragma: no cover - argparse enforces the valid subcommands
        raise RuntimeError(f"unsupported command: {args.command}")

    print(json.dumps(asdict(registration), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
