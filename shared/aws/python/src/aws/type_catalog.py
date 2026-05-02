from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .auth import build_aws_runtime, ensure_aws_profile, resolve_aws_region
from .device_catalog import (
    DeviceManifest,
    discover_repo_root,
    load_device_manifest,
)
from .thing_capabilities import capabilities_for_thing_type


TYPE_CATALOG_ROOT = "/txing"
TYPE_CATALOG_URI = "ssm:/txing"
SCHEMA_VERSION = "1.0"


class TypeCatalogError(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_slug(label: str, value: str) -> str:
    text = value.strip().lower()
    if not text:
        raise TypeCatalogError(f"{label} must be non-empty")
    if any(ch for ch in text if not (ch.isalnum() or ch == "-")):
        raise TypeCatalogError(f"{label} must contain only lowercase letters, numbers, or '-'")
    return text


def catalog_path(*parts: str) -> str:
    normalized_parts = [_normalize_slug("catalog path part", part) for part in parts]
    return "/".join((TYPE_CATALOG_ROOT, *normalized_parts))


def town_type_path() -> str:
    return catalog_path("town")


def rig_type_path(rig_type: str) -> str:
    return catalog_path("town", rig_type)


def device_type_path(rig_type: str, device_type: str) -> str:
    return catalog_path("town", rig_type, device_type)


def normalize_catalog_path(value: str) -> str:
    text = value.strip()
    if not text:
        return TYPE_CATALOG_ROOT
    if text.startswith("ssm:"):
        text = text.removeprefix("ssm:")
    if text == TYPE_CATALOG_ROOT or text.startswith(f"{TYPE_CATALOG_ROOT}/"):
        return text.rstrip("/")
    return f"{TYPE_CATALOG_ROOT}/{text.strip('/')}"


@dataclass(slots=True, frozen=True)
class RigTypeDefinition:
    rig_type: str
    display_name: str
    default_name: str
    capabilities: tuple[str, ...]
    host_services: tuple[str, ...] = ()


RIG_TYPE_DEFINITIONS: dict[str, RigTypeDefinition] = {
    "raspi": RigTypeDefinition(
        rig_type="raspi",
        display_name="Raspberry Pi Rig",
        default_name="server",
        capabilities=("sparkplug",),
        host_services=("bluetooth.service",),
    ),
    "cloud": RigTypeDefinition(
        rig_type="cloud",
        display_name="Cloud Rig",
        default_name="aws",
        capabilities=("sparkplug",),
    ),
}


def _base_record(kind: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "updatedAt": _utc_now_iso(),
    }


def _town_record(repo_root: Path) -> dict[str, Any]:
    record = _base_record("townType")
    record.update(
        {
            "path": town_type_path(),
            "thingType": "town",
            "displayName": "Town",
            "defaultName": "town",
            "capabilities": list(capabilities_for_thing_type("town", repo_root=repo_root)),
            "searchableAttributes": ["name"],
            "requiredAttributes": ["name", "shortId", "capabilities"],
        }
    )
    return record


def _rig_record(definition: RigTypeDefinition) -> dict[str, Any]:
    record = _base_record("rigType")
    record.update(
        {
            "path": rig_type_path(definition.rig_type),
            "thingType": "rig",
            "rigType": definition.rig_type,
            "displayName": definition.display_name,
            "defaultName": definition.default_name,
            "capabilities": list(definition.capabilities),
            "searchableAttributes": ["name", "townId", "rigType"],
            "requiredAttributes": [
                "name",
                "shortId",
                "townId",
                "rigType",
                "capabilities",
            ],
            "hostServices": list(definition.host_services),
        }
    )
    return record


def _device_record(manifest: DeviceManifest, *, rig_type: str) -> dict[str, Any]:
    record = _base_record("deviceType")
    record.update(
        {
            "path": device_type_path(rig_type, manifest.type),
            "thingType": manifest.type,
            "deviceType": manifest.type,
            "displayName": manifest.display_name,
            "defaultName": manifest.device_name,
            "rigType": rig_type,
            "capabilities": list(manifest.capabilities),
            "searchableAttributes": ["name", "townId", "rigId", "deviceType"],
            "requiredAttributes": [
                "name",
                "shortId",
                "townId",
                "rigId",
                "deviceType",
                "capabilities",
            ],
            "shadows": {
                shadow_name: {
                    "schema": str(contract.schema.relative_to(manifest.device_dir)),
                    "default": str(contract.default.relative_to(manifest.device_dir)),
                }
                for shadow_name, contract in manifest.shadows.items()
            },
            "web": {
                "adapter": manifest.web.adapter,
            },
        }
    )
    if manifest.board_video_channel_template is not None:
        record["resources"] = {
            "boardVideo": {
                "channelName": manifest.board_video_channel_template,
            }
        }
    return record


def build_type_records(*, repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = discover_repo_root(repo_root)
    records: dict[str, dict[str, Any]] = {town_type_path(): _town_record(root)}
    for definition in RIG_TYPE_DEFINITIONS.values():
        records[rig_type_path(definition.rig_type)] = _rig_record(definition)

    for device_type in ("unit", "time"):
        manifest = load_device_manifest(device_type, repo_root=root)
        for rig_type in manifest.compatible_rig_types:
            if rig_type not in RIG_TYPE_DEFINITIONS:
                raise TypeCatalogError(
                    f"Device type {manifest.type!r} references unknown rig type {rig_type!r}"
                )
            path = device_type_path(rig_type, manifest.type)
            records[path] = _device_record(manifest, rig_type=rig_type)
    return dict(sorted(records.items()))


class SsmTypeCatalog:
    def __init__(self, ssm_client: Any, *, repo_root: Path | None = None) -> None:
        self._ssm = ssm_client
        self._repo_root = discover_repo_root(repo_root)

    def expected_records(self) -> dict[str, dict[str, Any]]:
        return build_type_records(repo_root=self._repo_root)

    def put_record(self, path: str, record: dict[str, Any]) -> None:
        self._ssm.put_parameter(
            Name=normalize_catalog_path(path),
            Value=json.dumps(record, sort_keys=True, separators=(",", ":")),
            Type="String",
            Overwrite=True,
        )

    def sync(self) -> dict[str, dict[str, Any]]:
        records = self.expected_records()
        for path, record in records.items():
            self.put_record(path, record)
        return records

    def get_record(self, path: str) -> dict[str, Any]:
        normalized_path = normalize_catalog_path(path)
        try:
            response = self._ssm.get_parameter(Name=normalized_path)
        except Exception as err:
            code = getattr(err, "response", {}).get("Error", {}).get("Code")
            if code in {"ParameterNotFound", "ResourceNotFoundException", "NotFoundException"}:
                raise TypeCatalogError(
                    f"Missing SSM type catalog record {normalized_path!r}; run aws::type-sync"
                ) from err
            raise
        parameter = response.get("Parameter") or {}
        value = parameter.get("Value")
        if not isinstance(value, str) or not value.strip():
            raise TypeCatalogError(f"SSM type catalog record {normalized_path!r} is empty")
        try:
            record = json.loads(value)
        except json.JSONDecodeError as err:
            raise TypeCatalogError(
                f"SSM type catalog record {normalized_path!r} is not valid JSON: {err}"
            ) from err
        if not isinstance(record, dict):
            raise TypeCatalogError(f"SSM type catalog record {normalized_path!r} must be a JSON object")
        return record

    def get_rig_type(self, rig_type: str) -> dict[str, Any]:
        return self.get_record(rig_type_path(rig_type))

    def get_device_type(self, rig_type: str, device_type: str) -> dict[str, Any]:
        return self.get_record(device_type_path(rig_type, device_type))

    def list_records(self, path: str = TYPE_CATALOG_ROOT) -> list[tuple[str, dict[str, Any]]]:
        normalized_path = normalize_catalog_path(path)
        next_token: str | None = None
        rows: list[tuple[str, dict[str, Any]]] = []
        while True:
            request: dict[str, Any] = {
                "Path": normalized_path,
                "Recursive": True,
                "WithDecryption": False,
            }
            if next_token:
                request["NextToken"] = next_token
            response = self._ssm.get_parameters_by_path(**request)
            for parameter in response.get("Parameters", []):
                name = parameter.get("Name")
                value = parameter.get("Value")
                if not isinstance(name, str) or not isinstance(value, str):
                    continue
                rows.append((name, json.loads(value)))
            next_token = response.get("NextToken")
            if not isinstance(next_token, str) or not next_token:
                break
        return sorted(rows, key=lambda item: item[0])


def _build_catalog(*, region_name: str, repo_root: Path | None) -> SsmTypeCatalog:
    ensure_aws_profile("AWS_SELECTED_PROFILE", "AWS_TOWN_PROFILE")
    runtime = build_aws_runtime(region_name=region_name)
    return SsmTypeCatalog(runtime.client("ssm"), repo_root=repo_root)


def _print_records(records: Iterable[tuple[str, dict[str, Any]]]) -> None:
    print(
        json.dumps(
            [
                {
                    "path": path,
                    "kind": record.get("kind"),
                    "rigType": record.get("rigType"),
                    "deviceType": record.get("deviceType"),
                    "capabilities": record.get("capabilities"),
                }
                for path, record in records
            ],
            indent=2,
            sort_keys=True,
        )
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the hardcoded txing SSM type catalog")
    parser.add_argument("--region", default="")
    parser.add_argument("--repo-root", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync", help="Write the hardcoded /txing type catalog to SSM")
    list_parser = subparsers.add_parser("list", help="List SSM type catalog records")
    list_parser.add_argument("path", nargs="?", default=TYPE_CATALOG_ROOT)
    describe_parser = subparsers.add_parser("describe", help="Show one SSM type catalog record")
    describe_parser.add_argument("path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    region_name = args.region.strip() or resolve_aws_region()
    if not region_name:
        raise RuntimeError("AWS region is required; set AWS_REGION/AWS_DEFAULT_REGION or pass --region")
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    catalog = _build_catalog(region_name=region_name, repo_root=repo_root)

    if args.command == "sync":
        records = catalog.sync()
        _print_records(records.items())
    elif args.command == "list":
        _print_records(catalog.list_records(args.path))
    elif args.command == "describe":
        print(json.dumps(catalog.get_record(args.path), indent=2, sort_keys=True))
    else:  # pragma: no cover
        raise RuntimeError(f"unsupported command: {args.command}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
