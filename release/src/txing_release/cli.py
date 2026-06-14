#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

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


def print_versions() -> None:
    for component in COMPONENTS.values():
        print(f"{component.name}: {read_component_version(component)}")


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
    for path in component.node_packages:
        if set_json_package_version(path, target):
            changed.append(rel(path))
    for spec in component.text_versions:
        if set_text_version(spec, target):
            changed.append(rel(spec.path))

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

    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage txing release versions")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bump_parser = subparsers.add_parser("bump", help="bump or repair managed version surfaces")
    bump_parser.add_argument("component", choices=tuple(COMPONENTS))
    bump_parser.add_argument("version")
    subparsers.add_parser("print", help="print release component versions")
    args = parser.parse_args()

    if args.command == "bump":
        bump(args.component, args.version)
    elif args.command == "print":
        print_versions()
    else:
        parser.error(f"unsupported command {args.command!r}")


if __name__ == "__main__":
    main()
