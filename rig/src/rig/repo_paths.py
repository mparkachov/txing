from __future__ import annotations

import os
from pathlib import Path


def _is_repo_root(path: Path) -> bool:
    return (
        (path / "rig" / "pyproject.toml").is_file()
        and (path / "docs" / "txing-shadow.schema.json").is_file()
    )


def _discover_repo_root(
    *,
    cwd: Path,
    module_file: Path,
    env_repo_root: str | None,
) -> Path:
    if env_repo_root:
        return Path(env_repo_root).expanduser().resolve()

    resolved_cwd = cwd.resolve()
    seen: set[Path] = set()
    candidates = [resolved_cwd, *resolved_cwd.parents, *module_file.resolve().parents]
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_repo_root(candidate):
            return candidate
        if candidate.name == "rig" and (candidate / "pyproject.toml").is_file():
            return candidate.parent

    return resolved_cwd.parent if resolved_cwd.name == "rig" else resolved_cwd


REPO_ROOT = _discover_repo_root(
    cwd=Path.cwd(),
    module_file=Path(__file__),
    env_repo_root=os.environ.get("TXING_REPO_ROOT"),
)
DEFAULT_CERT_DIR = REPO_ROOT / "certs"
DEFAULT_IOT_ENDPOINT_FILE = DEFAULT_CERT_DIR / "iot-data-ats.endpoint"
