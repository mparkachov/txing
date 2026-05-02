from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import random
import re
from typing import Any, Mapping
import urllib.request

from .auth import AwsRuntime, build_aws_runtime, resolve_aws_region
from .sparkplug_shadow import (
    build_offline_device_shadow_payload,
    build_offline_node_shadow_payload,
    build_static_group_shadow_payload,
)
from .thing_capabilities import encode_capabilities_set, parse_capabilities_set
from .type_catalog import (
    SsmTypeCatalog,
    TypeCatalogError,
    device_type_path,
    rig_type_path,
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
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IOT_ATTRIBUTE_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_.,@/:#=\[\]-]*$")
TOWN_THING_TYPE = "town"
KIND_TOWN_TYPE = "townType"
KIND_RIG_TYPE = "rigType"
KIND_DEVICE_TYPE = "deviceType"
TOWN_ID_ATTRIBUTE = "townId"
RIG_ID_ATTRIBUTE = "rigId"
CFN_DISCHARGE_PHYSICAL_ID = "txing-discharge-things-on-delete"


LOGGER = logging.getLogger(__name__)


class EnlistError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class EnlistResult:
    thing_name: str
    thing_type_name: str
    created: bool
    attributes: dict[str, str]
    initialized_shadows: tuple[str, ...] = ()
    auxiliary_resources: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "thingName": self.thing_name,
            "thingTypeName": self.thing_type_name,
            "created": self.created,
            "attributes": self.attributes,
            "initializedShadows": list(self.initialized_shadows),
            "auxiliaryResources": self.auxiliary_resources or {},
        }


@dataclass(slots=True, frozen=True)
class DischargeResult:
    thing_name: str
    deleted: bool
    thing_type_name: str | None = None
    attributes: dict[str, str] | None = None
    deleted_shadows: tuple[str, ...] = ()
    detached_principals: tuple[str, ...] = ()
    auxiliary_resources: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "thingName": self.thing_name,
            "thingTypeName": self.thing_type_name,
            "deleted": self.deleted,
            "attributes": self.attributes or {},
            "deletedShadows": list(self.deleted_shadows),
            "detachedPrincipals": list(self.detached_principals),
            "auxiliaryResources": self.auxiliary_resources or {},
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error_code(error: Exception) -> str | None:
    return getattr(error, "response", {}).get("Error", {}).get("Code")


def _is_resource_not_found(error: Exception) -> bool:
    return _error_code(error) in RESOURCE_NOT_FOUND_CODES


def _normalize_slug(label: str, value: Any) -> str:
    if not isinstance(value, str):
        raise EnlistError(f"{label} must be a string")
    text = value.strip().lower()
    if not text:
        raise EnlistError(f"{label} must be non-empty")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text or not SLUG_PATTERN.fullmatch(text):
        raise EnlistError(f"{label} must normalize to {SLUG_PATTERN.pattern!r}; got {value!r}")
    return text


def _require_text(mapping: Mapping[str, Any], key: str, *, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EnlistError(f"{context} is missing required field {key!r}")
    return value.strip()


def _iot_attribute_value(label: str, value: str) -> str:
    if IOT_ATTRIBUTE_VALUE_PATTERN.fullmatch(value):
        return value
    encoded = re.sub(r"[^a-zA-Z0-9_.,@/:#=\[\]-]+", "-", value).strip("-")
    encoded = re.sub(r"-+", "-", encoded)
    if not encoded or not IOT_ATTRIBUTE_VALUE_PATTERN.fullmatch(encoded):
        raise EnlistError(
            f"IoT registry attribute {label!r} cannot be encoded into "
            f"{IOT_ATTRIBUTE_VALUE_PATTERN.pattern!r}: {value!r}"
        )
    return encoded


def _iot_attributes(attributes: Mapping[str, str]) -> dict[str, str]:
    return {key: _iot_attribute_value(key, value) for key, value in attributes.items()}


def _optional_text(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _list_value(record: Mapping[str, Any], key: str, *, context: str) -> tuple[str, ...]:
    value = record.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise EnlistError(f"{context} is missing required list field {key!r}")
    return tuple(value)


def _capabilities(record: Mapping[str, Any], *, context: str) -> tuple[str, ...]:
    return parse_capabilities_set(
        encode_capabilities_set(list(_list_value(record, "capabilities", context=context))),
        thing_name=context,
    )


def _thing_name_prefix(thing_type: str) -> str:
    return _normalize_slug("thing type", thing_type)


def _generate_short_id(rng: random.Random) -> str:
    return "".join(rng.choice(SHORT_ID_ALPHABET) for _ in range(SHORT_ID_LENGTH))


class EnlistService:
    def __init__(
        self,
        runtime: AwsRuntime,
        *,
        random_source: random.Random | None = None,
        type_catalog: SsmTypeCatalog | None = None,
    ) -> None:
        self._runtime = runtime
        self._rng = random_source or random.SystemRandom()
        self._iot = runtime.iot_client()
        self._iot_data: Any | None = None
        self._type_catalog = type_catalog or SsmTypeCatalog(runtime.client("ssm"))

    def handle(self, event: Mapping[str, Any]) -> dict[str, Any]:
        action = _require_text(event, "action", context="enlist event")
        if action == "enlistTown":
            return self.enlist_town(town_name=_require_text(event, "townName", context=action)).to_payload()
        if action == "enlistRig":
            return self.enlist_rig(
                town_id=_require_text(event, "townId", context=action),
                rig_type=_require_text(event, "rigType", context=action),
                rig_name=_require_text(event, "rigName", context=action),
            ).to_payload()
        if action == "enlistDevice":
            return self.enlist_device(
                rig_id=_require_text(event, "rigId", context=action),
                device_type=_require_text(event, "deviceType", context=action),
                device_name=_optional_text(event, "deviceName"),
            ).to_payload()
        if action == "assignDevice":
            return self.assign_device(
                device_id=_require_text(event, "deviceId", context=action),
                rig_id=_require_text(event, "rigId", context=action),
            ).to_payload()
        if action == "dischargeThing":
            return self.discharge_thing(
                thing_id=_require_text(event, "thingId", context=action),
            ).to_payload()
        if action == "dischargeAll":
            return self.discharge_all().to_payload()
        raise EnlistError(f"unsupported enlist action: {action!r}")

    def _iot_data_client(self) -> Any:
        if self._iot_data is None:
            self._iot_data = self._runtime.client(
                "iot-data",
                endpoint_url=f"https://{self._runtime.iot_data_endpoint()}",
            )
        return self._iot_data

    def _describe_thing(self, thing_name: str) -> dict[str, Any]:
        try:
            response = self._iot.describe_thing(thingName=thing_name)
        except Exception as error:
            if _is_resource_not_found(error):
                raise EnlistError(f"Thing {thing_name!r} is not registered") from error
            raise
        attributes = response.get("attributes")
        if not isinstance(attributes, dict):
            raise EnlistError(f"Thing {thing_name!r} returned invalid attributes")
        return response

    def _describe_thing_or_none(self, thing_name: str) -> dict[str, Any] | None:
        try:
            return self._describe_thing(thing_name)
        except EnlistError as error:
            if "is not registered" in str(error):
                return None
            raise

    def _thing_exists(self, thing_name: str) -> bool:
        try:
            self._iot.describe_thing(thingName=thing_name)
        except Exception as error:
            if _is_resource_not_found(error):
                return False
            raise
        return True

    def _allocate_thing_name(self, thing_type: str) -> tuple[str, str]:
        prefix = _thing_name_prefix(thing_type)
        for _ in range(256):
            short_id = _generate_short_id(self._rng)
            thing_name = f"{prefix}-{short_id}"
            if not self._thing_exists(thing_name):
                return thing_name, short_id
        raise EnlistError(f"failed to allocate a unique thing name for type {thing_type!r}")

    def _search_one(self, *, query: str, missing: str, multiple: str) -> dict[str, Any]:
        names: set[str] = set()
        next_token: str | None = None
        while True:
            request: dict[str, Any] = {
                "indexName": THING_INDEX_NAME,
                "queryString": query,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._iot.search_index(**request)
            for thing in response.get("things", []):
                if isinstance(thing, dict) and isinstance(thing.get("thingName"), str):
                    names.add(thing["thingName"])
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                break
        if not names:
            raise EnlistError(missing)
        if len(names) > 1:
            raise EnlistError(multiple)
        return self._describe_thing(next(iter(names)))

    def _search_thing_names(self, *, query: str) -> tuple[str, ...]:
        names: set[str] = set()
        next_token: str | None = None
        while True:
            request: dict[str, Any] = {
                "indexName": THING_INDEX_NAME,
                "queryString": query,
                "maxResults": 100,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self._iot.search_index(**request)
            for thing in response.get("things", []):
                if isinstance(thing, Mapping) and isinstance(thing.get("thingName"), str):
                    names.add(thing["thingName"])
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                break
        return tuple(sorted(names))

    def _find_town(self, town_name: str) -> dict[str, Any] | None:
        try:
            return self._search_one(
                query=(
                    f"thingTypeName:{TOWN_THING_TYPE} AND attributes.kind:{KIND_TOWN_TYPE} "
                    f"AND attributes.name:{town_name}"
                ),
                missing=f"Town {town_name!r} is not registered",
                multiple=f"Town {town_name!r} matched multiple things",
            )
        except EnlistError as error:
            if "is not registered" not in str(error):
                raise
            return None

    def _find_rig(self, *, town_id: str, rig_type: str, rig_name: str) -> dict[str, Any] | None:
        try:
            return self._search_one(
                query=(
                    f"thingTypeName:{rig_type} AND attributes.kind:{KIND_RIG_TYPE} "
                    f"AND attributes.name:{rig_name} "
                    f"AND attributes.{TOWN_ID_ATTRIBUTE}:{town_id}"
                ),
                missing=f"Rig {rig_name!r} is not registered under town {town_id!r}",
                multiple=f"Rig {rig_name!r} matched multiple things under town {town_id!r}",
            )
        except EnlistError as error:
            if "is not registered" not in str(error):
                raise
            return None

    def _find_device(self, *, rig_id: str, device_type: str, device_name: str) -> dict[str, Any] | None:
        try:
            return self._search_one(
                query=(
                    f"thingTypeName:{device_type} AND attributes.kind:{KIND_DEVICE_TYPE} "
                    f"AND attributes.name:{device_name} "
                    f"AND attributes.{RIG_ID_ATTRIBUTE}:{rig_id}"
                ),
                missing=f"Device {device_name!r} is not registered under rig {rig_id!r}",
                multiple=f"Device {device_name!r} matched multiple things under rig {rig_id!r}",
            )
        except EnlistError as error:
            if "is not registered" not in str(error):
                raise
            return None

    def _record_context(self, record: Mapping[str, Any]) -> str:
        path = record.get("path")
        return path if isinstance(path, str) else "type catalog record"

    def _base_attributes(
        self,
        *,
        record: Mapping[str, Any],
        name: str,
        short_id: str,
    ) -> dict[str, str]:
        context = self._record_context(record)
        kind = _require_text(record, "kind", context=context)
        type_path = _require_text(record, "path", context=context)
        display_name = _require_text(record, "displayName", context=context)
        capabilities = encode_capabilities_set(list(_capabilities(record, context=context)))
        return _iot_attributes(
            {
                "name": name,
                "shortId": short_id,
                "kind": kind,
                "typePath": type_path,
                "displayName": display_name,
                "capabilities": capabilities,
            }
        )

    def _update_thing_attributes(self, thing: Mapping[str, Any], attributes: dict[str, str]) -> None:
        request: dict[str, Any] = {
            "thingName": _require_text(thing, "thingName", context="thing"),
            "attributePayload": {
                "attributes": attributes,
                "merge": True,
            },
        }
        version = thing.get("version")
        if isinstance(version, int):
            request["expectedVersion"] = version
        self._iot.update_thing(**request)

    def _create_thing(
        self,
        *,
        thing_type: str,
        attributes: dict[str, str],
    ) -> tuple[dict[str, Any], bool]:
        thing_name, short_id = self._allocate_thing_name(thing_type)
        create_attributes = {**attributes, "shortId": short_id}
        self._iot.create_thing(
            thingName=thing_name,
            thingTypeName=thing_type,
            attributePayload={"attributes": create_attributes},
        )
        return self._describe_thing(thing_name), True

    def _ensure_shadow(self, thing_name: str, shadow_name: str, payload: dict[str, Any] | str) -> bool:
        client = self._iot_data_client()
        try:
            client.get_thing_shadow(thingName=thing_name, shadowName=shadow_name)
        except Exception as error:
            if not _is_resource_not_found(error):
                raise
            if isinstance(payload, str):
                payload_bytes = payload.encode("utf-8")
            else:
                payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
            client.update_thing_shadow(
                thingName=thing_name,
                shadowName=shadow_name,
                payload=payload_bytes,
            )
            return True
        return False

    def _delete_shadow(self, thing_name: str, shadow_name: str) -> bool:
        client = self._iot_data_client()
        try:
            client.delete_thing_shadow(thingName=thing_name, shadowName=shadow_name)
        except Exception as error:
            if _is_resource_not_found(error):
                return False
            raise
        return True

    def _shadow_records(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        shadows = record.get("shadows")
        return shadows if isinstance(shadows, Mapping) else {}

    def _initialize_town_shadows(self, thing_name: str) -> tuple[str, ...]:
        if self._ensure_shadow(thing_name, "sparkplug", build_static_group_shadow_payload(thing_name)):
            return ("sparkplug",)
        return ()

    def _initialize_rig_shadows(
        self,
        thing_name: str,
        *,
        town_id: str,
        rig_id: str,
    ) -> tuple[str, ...]:
        payload = build_offline_node_shadow_payload(group_id=town_id, edge_node_id=rig_id)
        if self._ensure_shadow(thing_name, "sparkplug", payload):
            return ("sparkplug",)
        return ()

    def _initialize_device_shadows(
        self,
        thing_name: str,
        *,
        record: Mapping[str, Any],
        town_id: str,
        rig_id: str,
    ) -> tuple[str, ...]:
        initialized: list[str] = []
        for shadow_name in _capabilities(record, context=self._record_context(record)):
            if shadow_name == "sparkplug":
                payload: dict[str, Any] | str = build_offline_device_shadow_payload(
                    group_id=town_id,
                    edge_node_id=rig_id,
                    device_id=thing_name,
                )
            else:
                shadow_record = self._shadow_records(record).get(shadow_name)
                if not isinstance(shadow_record, Mapping):
                    raise EnlistError(
                        f"type catalog record {self._record_context(record)!r} is missing shadow {shadow_name!r}"
                    )
                payload = _require_text(
                    shadow_record,
                    "defaultPayload",
                    context=f"shadow {shadow_name!r}",
                )
            if self._ensure_shadow(thing_name, shadow_name, payload):
                initialized.append(shadow_name)
        return tuple(initialized)

    def _ensure_board_video_resource(
        self,
        thing_name: str,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        resources = record.get("resources")
        if not isinstance(resources, Mapping):
            return {}
        board_video = resources.get("boardVideo")
        if not isinstance(board_video, Mapping):
            return {}
        template = _optional_text(board_video, "channelName")
        if template is None:
            return {}
        channel_name = template.replace("{device_id}", thing_name)
        client = self._runtime.client("kinesisvideo", region_name=self._runtime.region_name)
        created = False
        try:
            client.describe_signaling_channel(ChannelName=channel_name)
        except Exception as error:
            if not _is_resource_not_found(error):
                raise
            client.create_signaling_channel(
                ChannelName=channel_name,
                ChannelType="SINGLE_MASTER",
                SingleMasterConfiguration={"MessageTtlSeconds": 60},
            )
            created = True
        return {"boardVideo": {"channelName": channel_name, "created": created}}

    def _delete_board_video_resource(
        self,
        thing_name: str,
        attributes: Mapping[str, Any],
    ) -> dict[str, Any]:
        if attributes.get("kind") != KIND_DEVICE_TYPE:
            return {}
        rig_type = attributes.get("rigType")
        device_type = attributes.get("deviceType")
        if not isinstance(rig_type, str) or not isinstance(device_type, str):
            return {}
        try:
            record = self._type_catalog.get_device_type(rig_type, device_type)
        except Exception:
            return {}
        resources = record.get("resources")
        if not isinstance(resources, Mapping):
            return {}
        board_video = resources.get("boardVideo")
        if not isinstance(board_video, Mapping):
            return {}
        template = _optional_text(board_video, "channelName")
        if template is None:
            return {}
        channel_name = template.replace("{device_id}", thing_name)
        client = self._runtime.client("kinesisvideo", region_name=self._runtime.region_name)
        deleted = False
        missing = False
        try:
            response = client.describe_signaling_channel(ChannelName=channel_name)
            channel_arn = response.get("ChannelInfo", {}).get("ChannelARN")
            if not isinstance(channel_arn, str) or not channel_arn:
                channel_arn = response.get("ChannelARN")
            if not isinstance(channel_arn, str) or not channel_arn:
                raise EnlistError(f"KVS signaling channel {channel_name!r} did not return an ARN")
            client.delete_signaling_channel(ChannelARN=channel_arn)
            deleted = True
        except Exception as error:
            if not _is_resource_not_found(error):
                raise
            missing = True
        return {"boardVideo": {"channelName": channel_name, "deleted": deleted, "missing": missing}}

    def _thing_result(
        self,
        thing: Mapping[str, Any],
        *,
        created: bool,
        attributes: dict[str, str],
        initialized_shadows: tuple[str, ...] = (),
        auxiliary_resources: dict[str, Any] | None = None,
    ) -> EnlistResult:
        return EnlistResult(
            thing_name=_require_text(thing, "thingName", context="thing"),
            thing_type_name=_require_text(thing, "thingTypeName", context="thing"),
            created=created,
            attributes=attributes,
            initialized_shadows=initialized_shadows,
            auxiliary_resources=auxiliary_resources,
        )

    def enlist_town(self, *, town_name: str) -> EnlistResult:
        normalized_town_name = _normalize_slug("town name", town_name)
        record = self._type_catalog.get_record(town_type_path())
        existing = self._find_town(normalized_town_name)
        created = existing is None
        if existing is None:
            thing_name, short_id = self._allocate_thing_name(TOWN_THING_TYPE)
            attributes = self._base_attributes(
                record=record,
                name=normalized_town_name,
                short_id=short_id,
            )
            self._iot.create_thing(
                thingName=thing_name,
                thingTypeName=TOWN_THING_TYPE,
                attributePayload={"attributes": attributes},
            )
            thing = self._describe_thing(thing_name)
        else:
            current_attributes = existing.get("attributes", {})
            if not isinstance(current_attributes, Mapping):
                raise EnlistError(f"Thing {existing.get('thingName')!r} returned invalid attributes")
            short_id = _require_text(current_attributes, "shortId", context="town attributes")
            attributes = self._base_attributes(
                record=record,
                name=normalized_town_name,
                short_id=short_id,
            )
            self._update_thing_attributes(existing, attributes)
            thing = self._describe_thing(_require_text(existing, "thingName", context="town thing"))
        initialized = self._initialize_town_shadows(
            _require_text(thing, "thingName", context="town thing"),
        )
        return self._thing_result(
            thing,
            created=created,
            attributes=attributes,
            initialized_shadows=initialized,
        )

    def enlist_rig(self, *, town_id: str, rig_type: str, rig_name: str) -> EnlistResult:
        normalized_town_id = _normalize_slug("town id", town_id)
        normalized_rig_type = _normalize_slug("rig type", rig_type)
        normalized_rig_name = _normalize_slug("rig name", rig_name)
        town = self._describe_thing(normalized_town_id)
        if town.get("thingTypeName") != TOWN_THING_TYPE:
            raise EnlistError(f"Thing {normalized_town_id!r} is not a town")
        town_attributes = town.get("attributes", {})
        if not isinstance(town_attributes, Mapping):
            raise EnlistError(f"Town {normalized_town_id!r} returned invalid attributes")
        if town_attributes.get("kind") != KIND_TOWN_TYPE:
            raise EnlistError(f"Thing {normalized_town_id!r} is not a town")
        record = self._type_catalog.get_rig_type(normalized_rig_type)
        existing = self._find_rig(
            town_id=normalized_town_id,
            rig_type=normalized_rig_type,
            rig_name=normalized_rig_name,
        )
        created = existing is None
        host_services = _list_value(record, "hostServices", context=self._record_context(record)) if record.get("hostServices") else ()
        if existing is None:
            thing_name, short_id = self._allocate_thing_name(normalized_rig_type)
            attributes = {
                **self._base_attributes(record=record, name=normalized_rig_name, short_id=short_id),
                TOWN_ID_ATTRIBUTE: normalized_town_id,
                "rigType": normalized_rig_type,
            }
            if host_services:
                attributes["hostServices"] = ",".join(host_services)
            self._iot.create_thing(
                thingName=thing_name,
                thingTypeName=normalized_rig_type,
                attributePayload={"attributes": attributes},
            )
            thing = self._describe_thing(thing_name)
        else:
            current_attributes = existing.get("attributes", {})
            if not isinstance(current_attributes, Mapping):
                raise EnlistError(f"Thing {existing.get('thingName')!r} returned invalid attributes")
            short_id = _require_text(current_attributes, "shortId", context="rig attributes")
            attributes = {
                **self._base_attributes(record=record, name=normalized_rig_name, short_id=short_id),
                TOWN_ID_ATTRIBUTE: normalized_town_id,
                "rigType": normalized_rig_type,
            }
            if host_services:
                attributes["hostServices"] = ",".join(host_services)
            self._update_thing_attributes(existing, attributes)
            thing = self._describe_thing(_require_text(existing, "thingName", context="rig thing"))
        initialized = self._initialize_rig_shadows(
            _require_text(thing, "thingName", context="rig thing"),
            town_id=normalized_town_id,
            rig_id=_require_text(thing, "thingName", context="rig thing"),
        )
        return self._thing_result(
            thing,
            created=created,
            attributes=attributes,
            initialized_shadows=initialized,
        )

    def _device_record_for_rig(self, *, rig: Mapping[str, Any], device_type: str) -> dict[str, Any]:
        rig_type = _require_text(rig, "thingTypeName", context="rig thing")
        try:
            return self._type_catalog.get_device_type(rig_type, device_type)
        except TypeCatalogError as error:
            path = device_type_path(rig_type, device_type)
            raise EnlistError(
                f"Device type {device_type!r} is not compatible with rig type {rig_type!r}; "
                f"missing SSM type catalog record {path!r}"
            ) from error

    def enlist_device(
        self,
        *,
        rig_id: str,
        device_type: str,
        device_name: str | None = None,
    ) -> EnlistResult:
        normalized_rig_id = _normalize_slug("rig id", rig_id)
        normalized_device_type = _normalize_slug("device type", device_type)
        rig = self._describe_thing(normalized_rig_id)
        rig_attributes = rig.get("attributes", {})
        if not isinstance(rig_attributes, Mapping):
            raise EnlistError(f"Rig {normalized_rig_id!r} returned invalid attributes")
        if rig_attributes.get("kind") != KIND_RIG_TYPE:
            raise EnlistError(f"Thing {normalized_rig_id!r} is not a rig")
        town_id = _require_text(rig_attributes, TOWN_ID_ATTRIBUTE, context="rig attributes")
        town = self._describe_thing(town_id)
        town_attributes = town.get("attributes", {})
        if not isinstance(town_attributes, Mapping):
            raise EnlistError(f"Town {town_id!r} returned invalid attributes")
        if town_attributes.get("kind") != KIND_TOWN_TYPE:
            raise EnlistError(f"Thing {town_id!r} is not a town")
        record = self._device_record_for_rig(rig=rig, device_type=normalized_device_type)
        normalized_device_name = _normalize_slug(
            "device name",
            device_name or _require_text(record, "defaultName", context=self._record_context(record)),
        )
        existing = self._find_device(
            rig_id=normalized_rig_id,
            device_type=normalized_device_type,
            device_name=normalized_device_name,
        )
        created = existing is None
        rig_type = _require_text(rig, "thingTypeName", context="rig thing")
        if existing is None:
            thing_name, short_id = self._allocate_thing_name(normalized_device_type)
            attributes = {
                **self._base_attributes(record=record, name=normalized_device_name, short_id=short_id),
                TOWN_ID_ATTRIBUTE: town_id,
                RIG_ID_ATTRIBUTE: normalized_rig_id,
                "rigType": rig_type,
                "deviceType": normalized_device_type,
            }
            web = record.get("web")
            if isinstance(web, Mapping) and isinstance(web.get("adapter"), str):
                attributes["webAdapter"] = web["adapter"]
            self._iot.create_thing(
                thingName=thing_name,
                thingTypeName=normalized_device_type,
                attributePayload={"attributes": attributes},
            )
            thing = self._describe_thing(thing_name)
        else:
            current_attributes = existing.get("attributes", {})
            if not isinstance(current_attributes, Mapping):
                raise EnlistError(f"Thing {existing.get('thingName')!r} returned invalid attributes")
            short_id = _require_text(current_attributes, "shortId", context="device attributes")
            attributes = {
                **self._base_attributes(record=record, name=normalized_device_name, short_id=short_id),
                TOWN_ID_ATTRIBUTE: town_id,
                RIG_ID_ATTRIBUTE: normalized_rig_id,
                "rigType": rig_type,
                "deviceType": normalized_device_type,
            }
            web = record.get("web")
            if isinstance(web, Mapping) and isinstance(web.get("adapter"), str):
                attributes["webAdapter"] = web["adapter"]
            self._update_thing_attributes(existing, attributes)
            thing = self._describe_thing(_require_text(existing, "thingName", context="device thing"))
        thing_name = _require_text(thing, "thingName", context="device thing")
        initialized = self._initialize_device_shadows(
            thing_name,
            record=record,
            town_id=town_id,
            rig_id=normalized_rig_id,
        )
        auxiliary = self._ensure_board_video_resource(thing_name, record)
        return self._thing_result(
            thing,
            created=created,
            attributes=attributes,
            initialized_shadows=initialized,
            auxiliary_resources=auxiliary,
        )

    def assign_device(self, *, device_id: str, rig_id: str) -> EnlistResult:
        normalized_device_id = _normalize_slug("device id", device_id)
        normalized_rig_id = _normalize_slug("rig id", rig_id)
        device = self._describe_thing(normalized_device_id)
        rig = self._describe_thing(normalized_rig_id)
        device_attributes = device.get("attributes", {})
        rig_attributes = rig.get("attributes", {})
        if not isinstance(device_attributes, Mapping) or not isinstance(rig_attributes, Mapping):
            raise EnlistError("Device or rig returned invalid attributes")
        if rig_attributes.get("kind") != KIND_RIG_TYPE:
            raise EnlistError(f"Thing {normalized_rig_id!r} is not a rig")
        device_type = _require_text(device, "thingTypeName", context="device thing")
        record = self._device_record_for_rig(rig=rig, device_type=device_type)
        rig_type = _require_text(rig, "thingTypeName", context="rig thing")
        town_id = _require_text(rig_attributes, TOWN_ID_ATTRIBUTE, context="rig attributes")
        attributes = {
            **self._base_attributes(
                record=record,
                name=_require_text(device_attributes, "name", context="device attributes"),
                short_id=_require_text(device_attributes, "shortId", context="device attributes"),
            ),
            TOWN_ID_ATTRIBUTE: town_id,
            RIG_ID_ATTRIBUTE: normalized_rig_id,
            "rigType": rig_type,
            "deviceType": device_type,
        }
        web = record.get("web")
        if isinstance(web, Mapping) and isinstance(web.get("adapter"), str):
            attributes["webAdapter"] = web["adapter"]
        self._update_thing_attributes(device, attributes)
        updated_device = self._describe_thing(normalized_device_id)
        return self._thing_result(
            updated_device,
            created=False,
            attributes=attributes,
            initialized_shadows=(),
            auxiliary_resources={},
        )

    def _detach_thing_principals(self, thing_name: str) -> tuple[str, ...]:
        detached: list[str] = []
        next_token: str | None = None
        while True:
            request: dict[str, Any] = {"thingName": thing_name}
            if next_token:
                request["nextToken"] = next_token
            response = self._iot.list_thing_principals(**request)
            for principal in response.get("principals", []):
                if not isinstance(principal, str) or not principal:
                    continue
                try:
                    self._iot.detach_thing_principal(thingName=thing_name, principal=principal)
                except Exception as error:
                    if not _is_resource_not_found(error):
                        raise
                detached.append(principal)
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                break
        return tuple(detached)

    def discharge_thing(self, *, thing_id: str) -> DischargeResult:
        normalized_thing_id = _normalize_slug("thing id", thing_id)
        thing = self._describe_thing_or_none(normalized_thing_id)
        if thing is None:
            return DischargeResult(thing_name=normalized_thing_id, deleted=False)
        thing_name = _require_text(thing, "thingName", context="thing")
        thing_type_name = _require_text(thing, "thingTypeName", context="thing")
        raw_attributes = thing.get("attributes", {})
        if not isinstance(raw_attributes, Mapping):
            raise EnlistError(f"Thing {thing_name!r} returned invalid attributes")
        attributes = {str(key): str(value) for key, value in raw_attributes.items()}
        capabilities = tuple(
            parse_capabilities_set(
                _require_text(attributes, "capabilities", context=f"thing {thing_name!r} attributes"),
                thing_name=thing_name,
            )
        )
        deleted_shadows = tuple(
            shadow_name
            for shadow_name in capabilities
            if self._delete_shadow(thing_name, shadow_name)
        )
        detached_principals = self._detach_thing_principals(thing_name)
        auxiliary = self._delete_board_video_resource(thing_name, attributes)
        try:
            self._iot.delete_thing(thingName=thing_name)
        except Exception as error:
            if _is_resource_not_found(error):
                return DischargeResult(
                    thing_name=thing_name,
                    thing_type_name=thing_type_name,
                    deleted=False,
                    attributes=attributes,
                    deleted_shadows=deleted_shadows,
                    detached_principals=detached_principals,
                    auxiliary_resources=auxiliary,
                )
            raise
        return DischargeResult(
            thing_name=thing_name,
            thing_type_name=thing_type_name,
            deleted=True,
            attributes=attributes,
            deleted_shadows=deleted_shadows,
            detached_principals=detached_principals,
            auxiliary_resources=auxiliary,
        )

    def discharge_all(self) -> "DischargeAllResult":
        results: list[DischargeResult] = []
        for kind in (KIND_DEVICE_TYPE, KIND_RIG_TYPE, KIND_TOWN_TYPE):
            for thing_name in self._search_thing_names(query=f"attributes.kind:{kind}"):
                results.append(self.discharge_thing(thing_id=thing_name))
        return DischargeAllResult(tuple(results))


@dataclass(slots=True, frozen=True)
class DischargeAllResult:
    results: tuple[DischargeResult, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "deletedThings": [result.to_payload() for result in self.results],
            "deletedThingCount": sum(1 for result in self.results if result.deleted),
        }


def _send_cfn_response(
    event: Mapping[str, Any],
    context: Any,
    status: str,
    *,
    data: Mapping[str, Any] | None = None,
    reason: str | None = None,
    physical_resource_id: str | None = None,
) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason or f"See CloudWatch log stream: {context.log_stream_name}",
            "PhysicalResourceId": (
                physical_resource_id
                or event.get("PhysicalResourceId")
                or CFN_DISCHARGE_PHYSICAL_ID
            ),
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "NoEcho": False,
            "Data": dict(data or {}),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def _is_cfn_custom_resource_event(event: Mapping[str, Any]) -> bool:
    return (
        event.get("RequestType") in {"Create", "Update", "Delete"}
        and isinstance(event.get("ResponseURL"), str)
        and isinstance(event.get("ResourceProperties"), Mapping)
    )


def _handle_cfn_custom_resource(event: dict[str, Any], context: Any) -> dict[str, Any]:
    properties = event.get("ResourceProperties", {})
    physical_resource_id = (
        event.get("PhysicalResourceId")
        or properties.get("PhysicalResourceId")
        or CFN_DISCHARGE_PHYSICAL_ID
    )
    try:
        if properties.get("CleanupType") != "TxingDischargeThings":
            raise EnlistError(f"Unsupported CleanupType: {properties.get('CleanupType')!r}")
        data: dict[str, Any]
        if event.get("RequestType") == "Delete":
            region_name = resolve_aws_region()
            runtime = build_aws_runtime(region_name=region_name)
            data = EnlistService(runtime).discharge_all().to_payload()
        else:
            data = {"skipped": True}
        _send_cfn_response(
            event,
            context,
            "SUCCESS",
            data=data,
            physical_resource_id=str(physical_resource_id),
        )
        return {"ok": True, **data}
    except Exception as error:
        LOGGER.exception("Txing discharge custom resource failed")
        _send_cfn_response(
            event,
            context,
            "FAILED",
            reason=str(error),
            physical_resource_id=str(physical_resource_id),
        )
        return {
            "ok": False,
            "errorType": type(error).__name__,
            "message": str(error),
        }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        if _is_cfn_custom_resource_event(event):
            return _handle_cfn_custom_resource(event, context)
        region_name = resolve_aws_region()
        runtime = build_aws_runtime(region_name=region_name)
        result = EnlistService(runtime).handle(event)
        result["ok"] = True
        result["processedAt"] = _utc_now_iso()
        return result
    except Exception as error:
        return {
            "ok": False,
            "errorType": type(error).__name__,
            "message": str(error),
            "processedAt": _utc_now_iso(),
        }
