from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


class DeviceCatalogError(RuntimeError):
    pass


class DeviceTypeNotFoundError(DeviceCatalogError):
    pass


class DeviceManifestError(DeviceCatalogError):
    pass


def _normalize_path_anchor(anchor: Path | None) -> Path:
    candidate = (anchor or Path.cwd()).resolve()
    if candidate.is_file():
        return candidate.parent
    return candidate


def discover_repo_root(anchor: Path | None = None) -> Path:
    candidate = _normalize_path_anchor(anchor)
    for parent in (candidate, *candidate.parents):
        if (parent / "devices").is_dir() and (parent / "justfile").is_file():
            return parent
    raise DeviceCatalogError(
        f"Could not discover repo root from {candidate}"
    )


def _require_text(
    payload: dict[str, Any],
    key: str,
    *,
    manifest_file: Path,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DeviceManifestError(
            f"{manifest_file} is missing required non-empty string field {key!r}"
        )
    return value.strip()


def _optional_text(
    payload: dict[str, Any],
    key: str,
    *,
    manifest_file: Path,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DeviceManifestError(
            f"{manifest_file} field {key!r} must be a non-empty string when set"
        )
    return value.strip()


def _require_table(
    payload: dict[str, Any],
    key: str,
    *,
    manifest_file: Path,
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DeviceManifestError(f"{manifest_file} is missing required table {key!r}")
    return value


def _require_text_list(
    payload: dict[str, Any],
    key: str,
    *,
    manifest_file: Path,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise DeviceManifestError(
            f"{manifest_file} is missing required non-empty string array field {key!r}"
        )
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip() or item.strip() != item:
            raise DeviceManifestError(
                f"{manifest_file} field {key!r} must contain trimmed non-empty strings"
            )
        if item in seen:
            raise DeviceManifestError(
                f"{manifest_file} field {key!r} contains duplicate value {item!r}"
            )
        seen.add(item)
        values.append(item)
    return tuple(values)


def _validate_capabilities(
    capabilities: tuple[str, ...],
    *,
    manifest_file: Path,
) -> tuple[str, ...]:
    seen = set(capabilities)
    if "sparkplug" not in seen:
        raise DeviceManifestError(
            f"{manifest_file} capability list must include 'sparkplug'"
        )
    return capabilities


def _resolve_device_file(
    manifest_file: Path,
    raw_path: str,
) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = manifest_file.parent / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise DeviceManifestError(
            f"{manifest_file} references missing file {raw_path!r}"
        )
    return candidate


def _resolve_device_dir(
    manifest_file: Path,
    raw_path: str,
) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = manifest_file.parent / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise DeviceManifestError(
            f"{manifest_file} references missing directory {raw_path!r}"
        )
    return candidate


@dataclass(slots=True, frozen=True)
class DeviceShadowContract:
    name: str
    schema: Path
    default: Path

    def load_default_bytes(self) -> bytes:
        return self.default.read_bytes()


@dataclass(slots=True, frozen=True)
class RigProcessContract:
    name: str
    command: str
    args: tuple[str, ...]
    cwd: Path | None
    environment: tuple[str, ...]

    @property
    def argv(self) -> tuple[str, ...]:
        return (self.command, *self.args)


@dataclass(slots=True, frozen=True)
class DeviceWebContract:
    adapter: str


@dataclass(slots=True, frozen=True)
class DeviceManifest:
    type: str
    device_name: str
    display_name: str
    capabilities: tuple[str, ...]
    compatible_rig_types: tuple[str, ...]
    shadows: dict[str, DeviceShadowContract]
    rig_processes: tuple[RigProcessContract, ...]
    web: DeviceWebContract
    manifest_file: Path
    repo_root: Path
    board_video_channel_template: str | None = None

    @property
    def device_dir(self) -> Path:
        return self.manifest_file.parent

    @property
    def shadow_schema(self) -> Path:
        return self.shadow_contract("sparkplug").schema

    @property
    def default_shadow(self) -> Path:
        return self.shadow_contract("sparkplug").default

    @property
    def web_adapter(self) -> str:
        return self.web.adapter

    def shadow_contract(self, shadow_name: str) -> DeviceShadowContract:
        try:
            return self.shadows[shadow_name]
        except KeyError as err:
            raise DeviceManifestError(
                f"{self.manifest_file} has no shadow contract for {shadow_name!r}"
            ) from err

    def load_default_shadow_bytes(self, shadow_name: str = "sparkplug") -> bytes:
        return self.shadow_contract(shadow_name).load_default_bytes()

    def render_board_video_channel_name(self, *, device_id: str) -> str | None:
        template = self.board_video_channel_template
        if template is None:
            return None
        return template.format(device_id=device_id)


def _load_shadow_contracts(
    raw: dict[str, Any],
    *,
    manifest_file: Path,
    capabilities: tuple[str, ...],
) -> dict[str, DeviceShadowContract]:
    raw_shadows = _require_table(raw, "shadows", manifest_file=manifest_file)
    shadows: dict[str, DeviceShadowContract] = {}
    for shadow_name in capabilities:
        raw_shadow = raw_shadows.get(shadow_name)
        if not isinstance(raw_shadow, dict):
            raise DeviceManifestError(
                f"{manifest_file} is missing required table 'shadows.{shadow_name}'"
            )
        shadows[shadow_name] = DeviceShadowContract(
            name=shadow_name,
            schema=_resolve_device_file(
                manifest_file,
                _require_text(raw_shadow, "schema", manifest_file=manifest_file),
            ),
            default=_resolve_device_file(
                manifest_file,
                _require_text(raw_shadow, "default", manifest_file=manifest_file),
            ),
        )
    return shadows


def _load_rig_processes(
    raw: dict[str, Any],
    *,
    manifest_file: Path,
) -> tuple[RigProcessContract, ...]:
    raw_rig = raw.get("rig")
    if raw_rig is None:
        return ()
    if not isinstance(raw_rig, dict):
        raise DeviceManifestError(f"{manifest_file} field 'rig' must be a table")
    raw_processes = raw_rig.get("processes")
    if raw_processes is None:
        return ()
    if not isinstance(raw_processes, list):
        raise DeviceManifestError(
            f"{manifest_file} field 'rig.processes' must be an array of tables"
        )

    processes: list[RigProcessContract] = []
    seen: set[str] = set()
    for raw_process in raw_processes:
        if not isinstance(raw_process, dict):
            raise DeviceManifestError(
                f"{manifest_file} field 'rig.processes' must contain tables"
            )
        name = _require_text(raw_process, "name", manifest_file=manifest_file)
        if name in seen:
            raise DeviceManifestError(
                f"{manifest_file} field 'rig.processes' contains duplicate process {name!r}"
            )
        seen.add(name)
        raw_cwd = _optional_text(raw_process, "cwd", manifest_file=manifest_file)
        processes.append(
            RigProcessContract(
                name=name,
                command=_require_text(raw_process, "command", manifest_file=manifest_file),
                args=_require_text_list(raw_process, "args", manifest_file=manifest_file),
                cwd=_resolve_device_dir(manifest_file, raw_cwd) if raw_cwd else None,
                environment=_require_text_list(
                    raw_process,
                    "environment",
                    manifest_file=manifest_file,
                ),
            )
        )
    return tuple(processes)


def _load_web_contract(
    raw: dict[str, Any],
    *,
    manifest_file: Path,
) -> DeviceWebContract:
    raw_web = _require_table(raw, "web", manifest_file=manifest_file)
    return DeviceWebContract(
        adapter=_require_text(raw_web, "adapter", manifest_file=manifest_file),
    )


def _load_manifest(
    manifest_file: Path,
    *,
    repo_root: Path,
) -> DeviceManifest:
    try:
        raw = tomllib.loads(manifest_file.read_text(encoding="utf-8"))
    except OSError as err:
        raise DeviceManifestError(f"failed to read {manifest_file}: {err}") from err
    except tomllib.TOMLDecodeError as err:
        raise DeviceManifestError(f"failed to parse {manifest_file}: {err}") from err

    manifest_type = _require_text(raw, "type", manifest_file=manifest_file)
    device_name = _require_text(raw, "device_name", manifest_file=manifest_file)
    display_name = _require_text(raw, "display_name", manifest_file=manifest_file)
    capabilities = _validate_capabilities(
        _require_text_list(raw, "capabilities", manifest_file=manifest_file),
        manifest_file=manifest_file,
    )
    compatible_rig_types = _require_text_list(
        raw,
        "compatible_rig_types",
        manifest_file=manifest_file,
    )
    shadows = _load_shadow_contracts(
        raw,
        manifest_file=manifest_file,
        capabilities=capabilities,
    )
    rig_processes = _load_rig_processes(raw, manifest_file=manifest_file)
    web = _load_web_contract(raw, manifest_file=manifest_file)

    resources = raw.get("resources")
    board_video_channel_template: str | None = None
    if resources is not None:
        if not isinstance(resources, dict):
            raise DeviceManifestError(
                f"{manifest_file} field 'resources' must be a table"
            )
        board_video = resources.get("board_video")
        if board_video is not None:
            if not isinstance(board_video, dict):
                raise DeviceManifestError(
                    f"{manifest_file} field 'resources.board_video' must be a table"
                )
            board_video_channel_template = _require_text(
                board_video,
                "channel_name",
                manifest_file=manifest_file,
            )

    return DeviceManifest(
        type=manifest_type,
        device_name=device_name,
        display_name=display_name,
        capabilities=capabilities,
        compatible_rig_types=compatible_rig_types,
        shadows=shadows,
        rig_processes=rig_processes,
        web=web,
        manifest_file=manifest_file,
        repo_root=repo_root,
        board_video_channel_template=board_video_channel_template,
    )


def load_device_manifest(
    device_type: str,
    *,
    repo_root: Path | None = None,
) -> DeviceManifest:
    normalized_type = device_type.strip()
    if not normalized_type:
        raise DeviceTypeNotFoundError("device type must be non-empty")

    resolved_repo_root = discover_repo_root(repo_root)
    manifest_file = resolved_repo_root / "devices" / normalized_type / "manifest.toml"
    if not manifest_file.is_file():
        raise DeviceTypeNotFoundError(
            f"device type {normalized_type!r} is not registered"
        )
    return _load_manifest(manifest_file, repo_root=resolved_repo_root)


def list_loadable_device_types(*, repo_root: Path | None = None) -> list[str]:
    resolved_repo_root = discover_repo_root(repo_root)
    devices_dir = resolved_repo_root / "devices"
    if not devices_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in devices_dir.iterdir()
        if child.is_dir() and (child / "manifest.toml").is_file()
    )
