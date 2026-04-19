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
    DeviceTypeNotFoundError,
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
    device_id: str,
) -> str:
    value = normalize_registry_text(attributes.get(key))
    if value is None:
        raise DeviceRegistryError(
            f"Thing {device_id!r} is missing required IoT registry attribute {key!r}"
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


def build_device_id(device_type: str, short_id: str) -> str:
    return f"{device_type}-{short_id}"


@dataclass(slots=True, frozen=True)
class DeviceRegistration:
    device_id: str
    thing_name: str
    town_name: str
    rig_name: str
    device_type: str
    device_name: str
    short_id: str
    ble_device_id: str | None = None
    version: int | None = None


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

    def describe_device(self, device_id: str) -> DeviceRegistration:
        response = self._iot_client.describe_thing(thingName=device_id)
        attributes = response.get("attributes") or {}
        if not isinstance(attributes, dict):
            raise DeviceRegistryError(
                f"Thing {device_id!r} returned invalid IoT registry attributes"
            )
        return DeviceRegistration(
            device_id=device_id,
            thing_name=device_id,
            town_name=_require_registry_attribute(attributes, "town", device_id=device_id),
            rig_name=_require_registry_attribute(attributes, "rig", device_id=device_id),
            device_type=_require_registry_attribute(attributes, "deviceType", device_id=device_id),
            device_name=_require_registry_attribute(attributes, "deviceName", device_id=device_id),
            short_id=_require_registry_attribute(attributes, "shortId", device_id=device_id),
            ble_device_id=normalize_registry_text(attributes.get("bleDeviceId")),
            version=response.get("version"),
        )

    def _device_exists(self, device_id: str) -> bool:
        try:
            self._iot_client.describe_thing(thingName=device_id)
        except Exception as err:
            if _is_resource_not_found(err):
                return False
            raise
        return True

    def _allocate_device_id(self, device_type: str) -> tuple[str, str]:
        for _ in range(256):
            short_id = _generate_short_id(self._rng)
            device_id = build_device_id(device_type, short_id)
            if not self._device_exists(device_id):
                return device_id, short_id
        raise DeviceRegistryError(
            f"failed to allocate unique device id for device type {device_type!r}"
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
        query_string = f"attributes.rig:{normalized_rig_name}"
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

    def ensure_thing_type(self, device_type: str) -> None:
        normalized_device_type = _normalize_slug("device type", device_type)
        try:
            self._iot_client.describe_thing_type(thingTypeName=normalized_device_type)
            return
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
        self._iot_client.create_thing_type(
            thingTypeName=normalized_device_type,
            thingTypeProperties={
                "thingTypeDescription": (
                    f"Registered txing device type {normalized_device_type}"
                )
            },
        )

    def ensure_shadow_initialized(
        self,
        device_id: str,
        *,
        manifest: DeviceManifest,
    ) -> bool:
        try:
            self._iot_data().get_thing_shadow(thingName=device_id)
        except Exception as err:
            if not _is_resource_not_found(err):
                raise
            self._iot_data().update_thing_shadow(
                thingName=device_id,
                payload=manifest.load_default_shadow_bytes(),
            )
            return True
        return False

    def ensure_auxiliary_resources(
        self,
        device_id: str,
        *,
        manifest: DeviceManifest,
    ) -> None:
        channel_name = manifest.render_board_video_channel_name(device_id=device_id)
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
        device_id, short_id = self._allocate_device_id(normalized_device_type)
        self.ensure_thing_type(normalized_device_type)
        self._iot_client.create_thing(
            thingName=device_id,
            thingTypeName=normalized_device_type,
            attributePayload={
                "attributes": {
                    "town": normalized_town_name,
                    "rig": normalized_rig_name,
                    "deviceType": normalized_device_type,
                    "deviceName": manifest.device_name,
                    "shortId": short_id,
                }
            },
        )
        self.ensure_rig_group(normalized_rig_name)
        self.ensure_shadow_initialized(device_id, manifest=manifest)
        self.ensure_auxiliary_resources(device_id, manifest=manifest)
        return self.describe_device(device_id)

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
        description="Register and assign manifest-backed devices in AWS IoT",
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

    register_parser = subparsers.add_parser(
        "register",
        help="Create a new registered device and initialize its type resources",
    )
    register_parser.add_argument("--town", required=True)
    register_parser.add_argument("--rig", required=True)
    register_parser.add_argument("--device-type", required=True)

    assign_parser = subparsers.add_parser(
        "assign",
        help="Move an existing registered device to a new town/rig assignment",
    )
    assign_parser.add_argument("--device-id", required=True)
    assign_parser.add_argument("--town", required=True)
    assign_parser.add_argument("--rig", required=True)

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
    if args.command == "register":
        registration = registry.register_device(
            town_name=args.town,
            rig_name=args.rig,
            device_type=args.device_type,
        )
    elif args.command == "assign":
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
