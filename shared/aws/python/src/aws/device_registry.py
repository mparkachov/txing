from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import re
from typing import Any

from .auth import AwsRuntime, build_aws_runtime, ensure_aws_profile, resolve_aws_region
from .device_catalog import (
    DeviceManifest,
    discover_repo_root,
    load_device_manifest,
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
TOWN_THING_SEARCHABLE_ATTRIBUTES = (
    "name",
)
RIG_THING_SEARCHABLE_ATTRIBUTES = (
    "name",
    "town",
)
DEVICE_THING_SEARCHABLE_ATTRIBUTES = (
    "name",
    "town",
    "rig",
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


def build_rig_group_query(rig_name: str) -> str:
    normalized_rig_name = _normalize_slug("rig", rig_name)
    return f"attributes.rig:{normalized_rig_name} AND attributes.town:*"


def build_town_group_query(town_name: str) -> str:
    normalized_town_name = _normalize_slug("town", town_name)
    return f"thingTypeName:{RIG_THING_TYPE} AND attributes.town:{normalized_town_name}"


@dataclass(slots=True, frozen=True)
class ThingRegistration:
    thing_name: str
    thing_type: str
    name: str
    short_id: str
    town_name: str | None = None
    rig_name: str | None = None
    ble_device_id: str | None = None
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
    ) -> None:
        self._runtime = runtime
        self._repo_root = discover_repo_root(repo_root)
        self._rng = random_source or random.SystemRandom()
        self._iot_client = runtime.iot_client()
        self._iot_data_client: Any | None = None

    def _iot_data(self) -> Any:
        if self._iot_data_client is None:
            self._iot_data_client = self._runtime.client(
                "iot-data",
                endpoint_url=f"https://{self._runtime.iot_data_endpoint()}",
            )
        return self._iot_data_client

    def describe_thing(self, thing_name: str) -> ThingRegistration:
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
        town_name: str | None = None
        rig_name: str | None = None
        if thing_type == RIG_THING_TYPE:
            town_name = _require_registry_attribute(attributes, "town", thing_name=thing_name)
        elif thing_type != TOWN_THING_TYPE:
            town_name = _require_registry_attribute(attributes, "town", thing_name=thing_name)
            rig_name = _require_registry_attribute(attributes, "rig", thing_name=thing_name)
        return ThingRegistration(
            thing_name=thing_name,
            thing_type=thing_type,
            name=name,
            short_id=short_id,
            town_name=town_name,
            rig_name=rig_name,
            ble_device_id=normalize_registry_text(attributes.get("bleDeviceId")),
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
        return [self.describe_thing(thing_name) for thing_name in sorted(set(thing_names))]

    def _list_registry_things(self) -> list[ThingRegistration]:
        next_token: str | None = None
        registrations: list[ThingRegistration] = []
        while True:
            request: dict[str, Any] = {
                "maxResults": 100,
            }
            if next_token is not None:
                request["nextToken"] = next_token
            response = self._iot_client.list_things(**request)
            for thing in response.get("things", []):
                if not isinstance(thing, dict):
                    continue
                thing_name = normalize_registry_text(thing.get("thingName"))
                if thing_name is None:
                    continue
                registrations.append(self.describe_thing(thing_name))
            next_token = normalize_registry_text(response.get("nextToken"))
            if next_token is None:
                break
        return registrations

    def _find_things_in_registry(
        self,
        *,
        thing_type: str,
        name: str,
        town_name: str | None = None,
    ) -> list[ThingRegistration]:
        normalized_name = _normalize_slug("name", name)
        normalized_town_name = (
            _normalize_slug("town", town_name) if town_name is not None else None
        )
        matches: list[ThingRegistration] = []
        for registration in self._list_registry_things():
            if registration.thing_type != thing_type:
                continue
            if registration.name != normalized_name:
                continue
            if normalized_town_name is not None and registration.town_name != normalized_town_name:
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

    def describe_rig_by_name(self, *, town_name: str, rig_name: str) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        matches = self._search_index(
            f"thingTypeName:{RIG_THING_TYPE} AND attributes.name:{normalized_rig_name} AND attributes.town:{normalized_town_name}"
        )
        if not matches:
            matches = self._find_things_in_registry(
                thing_type=RIG_THING_TYPE,
                name=normalized_rig_name,
                town_name=normalized_town_name,
            )
        if not matches:
            raise DeviceRegistryError(
                f"Rig {normalized_rig_name!r} in town {normalized_town_name!r} is not registered in AWS IoT"
            )
        if len(matches) > 1:
            raise DeviceRegistryError(
                f"Rig {normalized_rig_name!r} in town {normalized_town_name!r} matched multiple AWS IoT things"
            )
        return matches[0]

    def ensure_town_group(self, town_name: str) -> None:
        normalized_town_name = _normalize_slug("town", town_name)
        properties = {
            "thingGroupDescription": f"Dynamic rig membership for town {normalized_town_name}",
            "attributePayload": {
                "attributes": {
                    "town": normalized_town_name,
                },
                "merge": True,
            },
        }
        query_string = build_town_group_query(normalized_town_name)
        try:
            self._iot_client.describe_thing_group(thingGroupName=normalized_town_name)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_client.create_dynamic_thing_group(
                thingGroupName=normalized_town_name,
                thingGroupProperties=properties,
                indexName=THING_INDEX_NAME,
                queryString=query_string,
            )
            return
        self._iot_client.update_dynamic_thing_group(
            thingGroupName=normalized_town_name,
            thingGroupProperties=properties,
            indexName=THING_INDEX_NAME,
            queryString=query_string,
        )

    def ensure_rig_group(self, rig_name: str) -> None:
        normalized_rig_name = _normalize_slug("rig", rig_name)
        properties = {
            "thingGroupDescription": f"Dynamic device membership for rig {normalized_rig_name}",
            "attributePayload": {
                "attributes": {
                    "rig": normalized_rig_name,
                },
                "merge": True,
            },
        }
        query_string = build_rig_group_query(normalized_rig_name)
        try:
            self._iot_client.describe_thing_group(thingGroupName=normalized_rig_name)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_client.create_dynamic_thing_group(
                thingGroupName=normalized_rig_name,
                thingGroupProperties=properties,
                indexName=THING_INDEX_NAME,
                queryString=query_string,
            )
            return

        self._iot_client.update_dynamic_thing_group(
            thingGroupName=normalized_rig_name,
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
            self._iot_data().update_thing_shadow(
                **kwargs,
                payload=payload,
            )
            return True
        return False

    def ensure_device_shadow_initialized(
        self,
        thing_name: str,
        *,
        manifest: DeviceManifest,
    ) -> bool:
        aws_dir = manifest.device_dir / "aws"
        initialized = False
        for shadow_name in ("sparkplug", "device", "mcu", "board"):
            initialized = (
                self.ensure_shadow_initialized(
                    thing_name,
                    shadow_name=shadow_name,
                    payload=(aws_dir / f"default-{shadow_name}-shadow.json").read_bytes(),
                )
                or initialized
            )
        return initialized

    def ensure_reported_only_shadow_initialized(
        self,
        thing_name: str,
        *,
        redcon: int,
    ) -> bool:
        payload = json.dumps(
            {
                "state": {
                    "reported": {
                        "redcon": redcon,
                    }
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        return self.ensure_shadow_initialized(
            thing_name,
            shadow_name="sparkplug",
            payload=payload,
        )

    def ensure_auxiliary_resources(
        self,
        thing_name: str,
        *,
        manifest: DeviceManifest,
    ) -> None:
        channel_name = manifest.render_board_video_channel_name(device_id=thing_name)
        if channel_name:
            self.ensure_signaling_channel(channel_name)

    def ensure_signaling_channel(self, channel_name: str) -> None:
        client = self._runtime.client(
            "kinesisvideo",
            region_name=self._runtime.region_name,
        )
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

    def register_town(
        self,
        *,
        town_name: str,
    ) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
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
                }
            },
        )
        self.ensure_town_group(normalized_town_name)
        self.ensure_reported_only_shadow_initialized(thing_name, redcon=1)
        return self.describe_thing(thing_name)

    def register_rig(
        self,
        *,
        town_name: str,
        rig_name: str,
    ) -> ThingRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        self.describe_town_by_name(normalized_town_name)
        self.ensure_thing_type(
            RIG_THING_TYPE,
            searchable_attributes=RIG_THING_SEARCHABLE_ATTRIBUTES,
            description="Registered txing rig type",
        )
        thing_name, short_id = self._allocate_thing_name(RIG_THING_TYPE)
        self._iot_client.create_thing(
            thingName=thing_name,
            thingTypeName=RIG_THING_TYPE,
            attributePayload={
                "attributes": {
                    "name": normalized_rig_name,
                    "shortId": short_id,
                    "town": normalized_town_name,
                }
            },
        )
        self.ensure_town_group(normalized_town_name)
        self.ensure_rig_group(normalized_rig_name)
        self.ensure_reported_only_shadow_initialized(thing_name, redcon=4)
        return self.describe_thing(thing_name)

    def register_device(
        self,
        *,
        town_name: str,
        rig_name: str,
        device_type: str,
    ) -> DeviceRegistration:
        manifest = load_device_manifest(device_type, repo_root=self._repo_root)
        normalized_town_name = _normalize_slug("town", town_name)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        normalized_device_type = _normalize_slug("device type", manifest.type)
        self.describe_town_by_name(normalized_town_name)
        self.describe_rig_by_name(
            town_name=normalized_town_name,
            rig_name=normalized_rig_name,
        )
        thing_name, short_id = self._allocate_thing_name(normalized_device_type)
        self.ensure_thing_type(
            normalized_device_type,
            searchable_attributes=DEVICE_THING_SEARCHABLE_ATTRIBUTES,
            description=f"Registered txing device type {normalized_device_type}",
        )
        self._iot_client.create_thing(
            thingName=thing_name,
            thingTypeName=normalized_device_type,
            attributePayload={
                "attributes": {
                    "town": normalized_town_name,
                    "rig": normalized_rig_name,
                    "name": manifest.device_name,
                    "shortId": short_id,
                }
            },
        )
        self.ensure_town_group(normalized_town_name)
        self.ensure_rig_group(normalized_rig_name)
        self.ensure_device_shadow_initialized(thing_name, manifest=manifest)
        self.ensure_auxiliary_resources(thing_name, manifest=manifest)
        return self.describe_device(thing_name)

    def assign_device(
        self,
        device_id: str,
        *,
        town_name: str,
        rig_name: str,
    ) -> DeviceRegistration:
        normalized_town_name = _normalize_slug("town", town_name)
        normalized_rig_name = _normalize_slug("rig", rig_name)
        registration = self.describe_device(device_id)
        self.describe_town_by_name(normalized_town_name)
        self.describe_rig_by_name(
            town_name=normalized_town_name,
            rig_name=normalized_rig_name,
        )
        self.ensure_town_group(normalized_town_name)
        self.ensure_rig_group(normalized_rig_name)
        request: dict[str, Any] = {
            "thingName": registration.device_id,
            "attributePayload": {
                "attributes": {
                    "town": normalized_town_name,
                    "rig": normalized_rig_name,
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

    register_rig_parser = subparsers.add_parser(
        "register-rig",
        help="Create a new registered rig thing and initialize its shadow",
    )
    register_rig_parser.add_argument("--town", required=True)
    register_rig_parser.add_argument("--rig", required=True)

    register_device_parser = subparsers.add_parser(
        "register-device",
        help="Create a new registered device thing and initialize its type resources",
    )
    register_device_parser.add_argument("--town", required=True)
    register_device_parser.add_argument("--rig", required=True)
    register_device_parser.add_argument("--device-type", required=True)

    register_alias_parser = subparsers.add_parser(
        "register",
        help="Deprecated alias for register-device",
    )
    register_alias_parser.add_argument("--town", required=True)
    register_alias_parser.add_argument("--rig", required=True)
    register_alias_parser.add_argument("--device-type", required=True)

    assign_parser = subparsers.add_parser(
        "assign-device",
        help="Move an existing registered device to a new town/rig assignment",
    )
    assign_parser.add_argument("--device-id", required=True)
    assign_parser.add_argument("--town", required=True)
    assign_parser.add_argument("--rig", required=True)

    assign_alias_parser = subparsers.add_parser(
        "assign",
        help="Deprecated alias for assign-device",
    )
    assign_alias_parser.add_argument("--device-id", required=True)
    assign_alias_parser.add_argument("--town", required=True)
    assign_alias_parser.add_argument("--rig", required=True)

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
    elif args.command == "register-rig":
        registration = registry.register_rig(
            town_name=args.town,
            rig_name=args.rig,
        )
    elif args.command in {"register-device", "register"}:
        registration = registry.register_device(
            town_name=args.town,
            rig_name=args.rig,
            device_type=args.device_type,
        )
    elif args.command in {"assign-device", "assign"}:
        registration = registry.assign_device(
            args.device_id,
            town_name=args.town,
            rig_name=args.rig,
        )
    else:  # pragma: no cover - argparse enforces the valid subcommands
        raise RuntimeError(f"unsupported command: {args.command}")

    print(json.dumps(asdict(registration), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
