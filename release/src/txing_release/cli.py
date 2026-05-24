#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

PYTHON_PROJECTS = (
    Path("shared/aws/python/pyproject.toml"),
)

PYTHON_LOCK_PACKAGES = (
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
        Path("devices/unit/daemon/internal/daemon/version.go"),
        "unit daemon Go version",
        re.compile(r'const packageVersion = "[^"]+"'),
        'const packageVersion = "{version}"',
    ),
    TextVersion(
        Path("devices/unit/board/kvs_master/include/kvs_master/version.hpp"),
        "board native KVS master version",
        re.compile(r'inline constexpr std::string_view kTxingUnitKvsMasterVersion = "[^"]+";'),
        'inline constexpr std::string_view kTxingUnitKvsMasterVersion = "{version}";',
    ),
    TextVersion(
        Path("devices/unit/board/hardware_worker/include/hardware_worker/version.hpp"),
        "unit hardware worker version",
        re.compile(r'#define TXING_UNIT_HARDWARE_WORKER_VERSION "[^"]+"'),
        '#define TXING_UNIT_HARDWARE_WORKER_VERSION "{version}"',
    ),
    TextVersion(
        Path("office/src/config.ts"),
        "office runtime fallback version",
        re.compile(r": '[0-9]+\.[0-9]+\.[0-9]+'"),
        ": '{version}'",
    ),
)


@dataclass(frozen=True)
class Component:
    name: str
    version_path: Path
    python_projects: tuple[Path, ...] = ()
    python_lock_packages: tuple[tuple[Path, tuple[str, ...]], ...] = ()
    node_packages: tuple[Path, ...] = ()
    text_versions: tuple[TextVersion, ...] = ()


COMPONENTS = {
    "rig": Component(
        name="rig",
        version_path=Path("release/versions/rig"),
    ),
    "lambda": Component(
        name="lambda",
        version_path=Path("release/versions/lambda"),
        python_projects=PYTHON_PROJECTS,
        python_lock_packages=PYTHON_LOCK_PACKAGES,
    ),
    "unit": Component(
        name="unit",
        version_path=Path("release/versions/unit"),
        text_versions=TEXT_VERSIONS[:3],
    ),
    "office": Component(
        name="office",
        version_path=Path("release/versions/office"),
        node_packages=NODE_PACKAGES,
        text_versions=TEXT_VERSIONS[3:],
    ),
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


def read_component_version(component: Component) -> str:
    value = read_text(component.version_path).strip()
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


def refresh_lockfiles(component: Component) -> None:
    for pyproject in component.python_projects:
        run(["uv", "lock", "--project", str(ROOT / pyproject.parent)])


def component_names() -> str:
    return ", ".join(COMPONENTS)


def parse_component(name: str) -> Component:
    component = COMPONENTS.get(name)
    if component is None:
        raise SystemExit(f"unknown component {name!r}; expected one of: {component_names()}")
    return component


def print_component_audit(component: Component, version: str) -> list[str]:
    reports: list[str] = []
    problems = collect_version_problems(component, reports)
    print(f"{component.name} managed version sources:")
    for report in reports:
        print(f"  {report}")
    if problems:
        print(f"{component.name} version consistency warnings:", file=sys.stderr)
        for problem in problems:
            print(f"warning: {problem}", file=sys.stderr)
    else:
        print(f"all {component.name} managed version surfaces match {version}")
    return problems


def bump(component_name: str, target: str) -> None:
    component = parse_component(component_name)
    target_tuple = validate_semver(target)
    current = read_component_version(component)
    current_tuple = validate_semver(current)
    if target_tuple < current_tuple:
        raise SystemExit(f"refusing {component.name} downgrade from {current} to {target}")

    if target_tuple == current_tuple:
        print_component_audit(component, target)
        return

    changed: list[str] = []
    if write_text_if_changed(component.version_path, target + "\n"):
        changed.append(rel(component.version_path))
    for path in component.python_projects:
        if set_toml_package_version(path, target):
            changed.append(rel(path))
    for path in component.node_packages:
        if set_json_package_version(path, target):
            changed.append(rel(path))
    for spec in component.text_versions:
        if set_text_version(spec, target):
            changed.append(rel(spec.path))

    refresh_lockfiles(component)
    problems = collect_version_problems(component)
    if problems:
        print(f"{component.name} version consistency warnings:", file=sys.stderr)
        for problem in problems:
            print(f"warning: {problem}", file=sys.stderr)

    if changed:
        print(f"updated {component.name} version surfaces:")
        for item in changed:
            print(f"  {item}")
    else:
        print(f"all {component.name} managed version surfaces already at {target}")


def load_toml(path: Path) -> dict:
    return tomllib.loads(read_text(path))


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


def collect_version_problems(component: Component, reports: list[str] | None = None) -> list[str]:
    expected = read_component_version(component)
    problems: list[str] = []
    if reports is not None:
        reports.append(f"{rel(component.version_path)}: {expected!r}")

    for path in component.python_projects:
        check_value(
            problems,
            f"{rel(path)} project.version",
            value_at(load_toml(path), ("project", "version")),
            expected,
            reports,
        )
    for path in component.node_packages:
        payload = json.loads(read_text(path))
        check_value(problems, f"{rel(path)} version", payload.get("version"), expected, reports)
    for spec in component.text_versions:
        check_value(
            problems,
            f"{rel(spec.path)} {spec.label}",
            text_version_value(spec),
            expected,
            reports,
        )

    for lock_path, package_names in component.python_lock_packages:
        check_uv_lock(problems, lock_path, package_names, expected, reports)
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage txing release versions")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bump_parser = subparsers.add_parser("bump", help="bump or repair managed version surfaces")
    bump_parser.add_argument("component", choices=tuple(COMPONENTS))
    bump_parser.add_argument("version")
    args = parser.parse_args()

    if args.command == "bump":
        bump(args.component, args.version)
    else:
        parser.error(f"unsupported command {args.command!r}")


if __name__ == "__main__":
    main()
