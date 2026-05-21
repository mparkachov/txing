#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

RIG_PACKAGES = (
    "txing-aws-connectivity",
    "txing-ble-connectivity",
    "txing-capability-protocol",
    "txing-rig-local-pubsub",
    "txing-sparkplug-manager",
)

STANDALONE_CARGO_MANIFESTS = (
    Path("devices/unit/daemon/Cargo.toml"),
    Path("devices/power/test/Cargo.toml"),
    Path("devices/weather/test/Cargo.toml"),
)

PYTHON_PROJECTS = (
    Path("release/pyproject.toml"),
    Path("shared/aws/python/pyproject.toml"),
)

PYTHON_LOCK_PACKAGES = (
    (Path("release/uv.lock"), ("txing-release",)),
    (Path("shared/aws/python/uv.lock"), ("aws",)),
)

NODE_PACKAGES = (
    Path("office/package.json"),
    )


@dataclass(frozen=True)
class TextVersion:
    path: Path
    label: str
    pattern: re.Pattern[str]
    replacement: str
    count: int = 1


TEXT_VERSIONS = (
    TextVersion(
        Path("devices/unit/board/kvs_master/include/kvs_master/version.hpp"),
        "board native KVS master version",
        re.compile(r'inline constexpr std::string_view kTxingBoardKvsMasterVersion = "[^"]+";'),
        'inline constexpr std::string_view kTxingBoardKvsMasterVersion = "{version}";',
    ),
    TextVersion(
        Path("office/src/config.ts"),
        "office runtime fallback version",
        re.compile(r": '[0-9]+\.[0-9]+\.[0-9]+'"),
        ": '{version}'",
    ),
    TextVersion(
        Path("office/vite.config.ts"),
        "office vite fallback version",
        re.compile(r"'[0-9]+\.[0-9]+\.[0-9]+'"),
        "'{version}'",
        0,
    ),
)

SCAN_IGNORED_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "node_modules",
    "target",
}

SCAN_IGNORED_PREFIXES = (
    Path("devices/common/mcu/ncs"),
)

SCAN_EXTENSIONS = {
    ".json",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}


def rel(path: Path) -> str:
    if not path.is_absolute():
        return str(path)
    return str(path.relative_to(ROOT))


def validate_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise SystemExit(f"version must be strict semver MAJOR.MINOR.PATCH, got {value!r}")
    return tuple(int(part) for part in match.groups())


def read_text(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write_text_if_changed(path: Path, content: str) -> bool:
    full_path = ROOT / path
    old = full_path.read_text(encoding="utf-8") if full_path.exists() else None
    if old == content:
        return False
    full_path.write_text(content, encoding="utf-8")
    return True


def read_root_version() -> str:
    value = read_text(Path("VERSION")).strip()
    validate_semver(value)
    return value


def replace_pattern(path: Path, pattern: re.Pattern[str], replacement: str, *, count: int = 1) -> bool:
    content = read_text(path)
    updated, replacements = pattern.subn(replacement, content, count=count)
    if replacements < 1:
        raise SystemExit(f"{rel(path)} does not contain expected version pattern")
    return write_text_if_changed(path, updated)


def set_toml_package_version(path: Path, version: str) -> bool:
    return replace_pattern(
        path,
        re.compile(r'(?m)^version\s*=\s*"[^"]+"$'),
        f'version = "{version}"',
    )


def set_json_package_version(path: Path, version: str) -> bool:
    full_path = ROOT / path
    payload = json.loads(full_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{rel(path)} must contain a JSON object")
    payload["version"] = version
    return write_text_if_changed(path, json.dumps(payload, indent=2) + "\n")


def set_text_version(spec: TextVersion, version: str) -> bool:
    return replace_pattern(
        spec.path,
        spec.pattern,
        spec.replacement.format(version=version),
        count=spec.count,
    )


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def refresh_lockfiles() -> None:
    cargo_manifests = [Path("rig/Cargo.toml"), *STANDALONE_CARGO_MANIFESTS]
    for manifest in cargo_manifests:
        run(["cargo", "generate-lockfile", "--manifest-path", str(ROOT / manifest)])
    for pyproject in PYTHON_PROJECTS:
        run(["uv", "lock", "--project", str(ROOT / pyproject.parent)])


def managed_version_paths() -> set[Path]:
    paths: set[Path] = {
        Path("VERSION"),
        Path("rig/Cargo.toml"),
        Path("rig/Cargo.lock"),
        *STANDALONE_CARGO_MANIFESTS,
        *PYTHON_PROJECTS,
        *NODE_PACKAGES,
        *(spec.path for spec in TEXT_VERSIONS),
    }
    paths.update(manifest.parent / "Cargo.lock" for manifest in STANDALONE_CARGO_MANIFESTS)
    paths.update(pyproject.parent / "uv.lock" for pyproject in PYTHON_PROJECTS)
    return paths


def path_is_under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def should_scan_path(path: Path, managed_paths: set[Path]) -> bool:
    if path in managed_paths:
        return False
    if any(path_is_under(path, prefix) for prefix in SCAN_IGNORED_PREFIXES):
        return False
    if path.name in {"Cargo.lock", "uv.lock", "bun.lock", "bun.lockb", "package-lock.json"}:
        return False
    if path.name == "justfile":
        return True
    return path.suffix in SCAN_EXTENSIONS


def collect_unmanaged_version_occurrences(version: str) -> list[str]:
    managed_paths = managed_version_paths()
    occurrences: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in SCAN_IGNORED_DIRS
            and not any(path_is_under(rel_dir / dirname, prefix) for prefix in SCAN_IGNORED_PREFIXES)
        ]
        for filename in filenames:
            rel_path = rel_dir / filename
            if not should_scan_path(rel_path, managed_paths):
                continue
            try:
                lines = (ROOT / rel_path).read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if version in line:
                    excerpt = line.strip()
                    if len(excerpt) > 160:
                        excerpt = excerpt[:157] + "..."
                    occurrences.append(f"{rel(rel_path)}:{line_number}: {excerpt}")
    return occurrences


def bump(target: str) -> None:
    target_tuple = validate_semver(target)
    current = read_root_version()
    current_tuple = validate_semver(current)
    if target_tuple < current_tuple:
        raise SystemExit(f"refusing downgrade from {current} to {target}")

    changed: list[str] = []
    if write_text_if_changed(Path("VERSION"), target + "\n"):
        changed.append("VERSION")
    if set_toml_package_version(Path("rig/Cargo.toml"), target):
        changed.append("rig/Cargo.toml")
    for path in STANDALONE_CARGO_MANIFESTS:
        if set_toml_package_version(path, target):
            changed.append(rel(path))
    for path in PYTHON_PROJECTS:
        if set_toml_package_version(path, target):
            changed.append(rel(path))
    for path in NODE_PACKAGES:
        if set_json_package_version(path, target):
            changed.append(rel(path))
    for spec in TEXT_VERSIONS:
        if set_text_version(spec, target):
            changed.append(rel(spec.path))

    refresh_lockfiles()
    problems = collect_version_problems()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        raise SystemExit(1)

    if target_tuple > current_tuple:
        occurrences = collect_unmanaged_version_occurrences(current)
        if occurrences:
            print(
                f"unmanaged occurrences of previous release {current} found for review:",
                file=sys.stderr,
            )
            for occurrence in occurrences:
                print(f"  {occurrence}", file=sys.stderr)

    if changed:
        print("updated version surfaces:")
        for item in changed:
            print(f"  {item}")
    else:
        print(f"all managed version surfaces already at {target}")


def load_toml(path: Path) -> dict:
    return tomllib.loads(read_text(path))


def toml_package_name(path: Path) -> str:
    package = load_toml(path).get("package")
    if not isinstance(package, dict) or not isinstance(package.get("name"), str):
        raise SystemExit(f"{rel(path)} is missing [package].name")
    return package["name"]


def toml_project_name(path: Path) -> str:
    project = load_toml(path).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise SystemExit(f"{rel(path)} is missing [project].name")
    return project["name"]


def value_at(data: dict, path: tuple[str, ...]) -> str | None:
    value: object = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, str) else None


def check_value(
    problems: list[str],
    label: str,
    actual: str | None,
    expected: str,
    reports: list[str] | None = None,
) -> None:
    if reports is not None:
        reports.append(f"{label}: {actual!r}")
    if actual != expected:
        problems.append(f"{label}: expected {expected}, got {actual!r}")


def check_cargo_lock(
    problems: list[str],
    lock_path: Path,
    package_names: tuple[str, ...],
    expected: str,
    reports: list[str] | None = None,
) -> None:
    full_path = ROOT / lock_path
    if not full_path.exists():
        problems.append(f"{rel(lock_path)}: missing Cargo lockfile")
        return
    payload = tomllib.loads(full_path.read_text(encoding="utf-8"))
    packages = payload.get("package")
    if not isinstance(packages, list):
        problems.append(f"{rel(lock_path)}: missing package entries")
        return
    versions = {
        package.get("name"): package.get("version")
        for package in packages
        if isinstance(package, dict)
    }
    for name in package_names:
        check_value(
            problems,
            f"{rel(lock_path)} package {name}",
            versions.get(name),
            expected,
            reports,
        )


def check_uv_lock(
    problems: list[str],
    lock_path: Path,
    package_names: tuple[str, ...],
    expected: str,
    reports: list[str] | None = None,
) -> None:
    full_path = ROOT / lock_path
    if not full_path.exists():
        problems.append(f"{rel(lock_path)}: missing uv lockfile")
        return
    payload = tomllib.loads(full_path.read_text(encoding="utf-8"))
    packages = payload.get("package")
    if not isinstance(packages, list):
        problems.append(f"{rel(lock_path)}: missing package entries")
        return
    versions = {
        package.get("name"): package.get("version")
        for package in packages
        if isinstance(package, dict)
    }
    for name in package_names:
        check_value(
            problems,
            f"{rel(lock_path)} package {name}",
            versions.get(name),
            expected,
            reports,
        )


def text_version_value(spec: TextVersion) -> str | None:
    content = read_text(spec.path)
    match = spec.pattern.search(content)
    if not match:
        return None
    version_match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+", match.group(0))
    return version_match.group(0) if version_match else None


def collect_version_problems(reports: list[str] | None = None) -> list[str]:
    expected = read_root_version()
    problems: list[str] = []
    if reports is not None:
        reports.append(f"VERSION: {expected!r}")

    rig_workspace = load_toml(Path("rig/Cargo.toml"))
    check_value(
        problems,
        "rig/Cargo.toml workspace.package.version",
        value_at(rig_workspace, ("workspace", "package", "version")),
        expected,
        reports,
    )
    for path in STANDALONE_CARGO_MANIFESTS:
        check_value(
            problems,
            f"{rel(path)} package.version",
            value_at(load_toml(path), ("package", "version")),
            expected,
            reports,
        )
    for path in PYTHON_PROJECTS:
        check_value(
            problems,
            f"{rel(path)} project.version",
            value_at(load_toml(path), ("project", "version")),
            expected,
            reports,
        )
    for path in NODE_PACKAGES:
        payload = json.loads(read_text(path))
        check_value(problems, f"{rel(path)} version", payload.get("version"), expected, reports)
    for spec in TEXT_VERSIONS:
        check_value(
            problems,
            f"{rel(spec.path)} {spec.label}",
            text_version_value(spec),
            expected,
            reports,
        )

    check_cargo_lock(problems, Path("rig/Cargo.lock"), RIG_PACKAGES, expected, reports)
    for manifest in STANDALONE_CARGO_MANIFESTS:
        package_name = toml_package_name(manifest)
        check_cargo_lock(
            problems,
            manifest.parent / "Cargo.lock",
            (package_name,),
            expected,
            reports,
        )

    for lock_path, package_names in PYTHON_LOCK_PACKAGES:
        check_uv_lock(problems, lock_path, package_names, expected, reports)
    return problems


def check() -> None:
    reports: list[str] = []
    problems = collect_version_problems(reports)
    print("managed version sources:")
    for report in reports:
        print(f"  {report}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        raise SystemExit(1)
    print(f"all managed version surfaces match {read_root_version()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage txing release versions")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bump_parser = subparsers.add_parser("bump", help="bump or repair managed version surfaces")
    bump_parser.add_argument("version")
    subparsers.add_parser("check", help="verify managed version surfaces")
    args = parser.parse_args()

    if args.command == "bump":
        bump(args.version)
    elif args.command == "check":
        check()
    else:
        parser.error(f"unsupported command {args.command!r}")


if __name__ == "__main__":
    main()
