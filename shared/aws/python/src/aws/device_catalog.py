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


@dataclass(slots=True, frozen=True)
class DeviceManifest:
    type: str
    device_name: str
    display_name: str
    shadow_schema: Path
    default_shadow: Path
    rig_adapter: str
    web_adapter: str
    manifest_file: Path
    repo_root: Path
    board_video_channel_template: str | None = None

    @property
    def device_dir(self) -> Path:
        return self.manifest_file.parent

    def load_default_shadow_bytes(self) -> bytes:
        return self.default_shadow.read_bytes()

    def render_board_video_channel_name(self, *, device_id: str) -> str | None:
        template = self.board_video_channel_template
        if template is None:
            return None
        return template.format(device_id=device_id)


def _resolve_repo_file(
    repo_root: Path,
    manifest_file: Path,
    raw_path: str,
) -> Path:
    candidate = (repo_root / raw_path).resolve()
    if not candidate.is_file():
        raise DeviceManifestError(
            f"{manifest_file} references missing file {raw_path!r}"
        )
    return candidate


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
    shadow_schema = _resolve_repo_file(
        repo_root,
        manifest_file,
        _require_text(raw, "shadow_schema", manifest_file=manifest_file),
    )
    default_shadow = _resolve_repo_file(
        repo_root,
        manifest_file,
        _require_text(raw, "default_shadow", manifest_file=manifest_file),
    )
    rig_adapter = _require_text(raw, "rig_adapter", manifest_file=manifest_file)
    web_adapter = _require_text(raw, "web_adapter", manifest_file=manifest_file)

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
        shadow_schema=shadow_schema,
        default_shadow=default_shadow,
        rig_adapter=rig_adapter,
        web_adapter=web_adapter,
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
