from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device_catalog import discover_repo_root


CAPABILITIES_ATTRIBUTE = "capabilitiesSet"
CAPABILITY_DEFINITION_FILE = Path("shared/aws/thing-type-capabilities.json")
KNOWN_NAMED_SHADOW_CAPABILITIES = (
    "sparkplug",
    "mcu",
    "board",
    "video",
)


class ThingCapabilitiesError(RuntimeError):
    pass


def encode_capabilities_set(capabilities: tuple[str, ...] | list[str]) -> str:
    if not capabilities:
        raise ThingCapabilitiesError("capability set must not be empty")
    return ",".join(capabilities)


def parse_capabilities_set(
    value: Any,
    *,
    thing_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        raise ThingCapabilitiesError(
            f"Thing {thing_name!r} is missing required IoT registry attribute "
            f"{CAPABILITIES_ATTRIBUTE!r}"
        )
    parts = value.split(",")
    capabilities: list[str] = []
    seen: set[str] = set()
    for raw_part in parts:
        capability = raw_part.strip()
        if not capability:
            raise ThingCapabilitiesError(
                f"Thing {thing_name!r} has malformed {CAPABILITIES_ATTRIBUTE!r}: {value!r}"
            )
        if capability != raw_part:
            raise ThingCapabilitiesError(
                f"Thing {thing_name!r} has malformed {CAPABILITIES_ATTRIBUTE!r}: {value!r}"
            )
        if capability not in KNOWN_NAMED_SHADOW_CAPABILITIES:
            raise ThingCapabilitiesError(
                f"Thing {thing_name!r} has unsupported capability {capability!r}"
            )
        if capability in seen:
            raise ThingCapabilitiesError(
                f"Thing {thing_name!r} has duplicate capability {capability!r}"
            )
        seen.add(capability)
        capabilities.append(capability)
    if "sparkplug" not in seen:
        raise ThingCapabilitiesError(
            f"Thing {thing_name!r} capability set must include 'sparkplug'"
        )
    return tuple(capabilities)


def load_thing_type_capabilities(
    *,
    repo_root: Path | None = None,
) -> dict[str, tuple[str, ...]]:
    root = discover_repo_root(repo_root)
    definition_file = root / CAPABILITY_DEFINITION_FILE
    try:
        payload = json.loads(definition_file.read_text(encoding="utf-8"))
    except OSError as err:
        raise ThingCapabilitiesError(
            f"failed to read thing capability definition {definition_file}: {err}"
        ) from err
    except json.JSONDecodeError as err:
        raise ThingCapabilitiesError(
            f"thing capability definition {definition_file} is not valid JSON: {err}"
        ) from err
    if not isinstance(payload, dict):
        raise ThingCapabilitiesError(
            f"thing capability definition {definition_file} must be a JSON object"
        )

    definitions: dict[str, tuple[str, ...]] = {}
    for thing_type, raw_capabilities in payload.items():
        if not isinstance(thing_type, str) or not thing_type.strip():
            raise ThingCapabilitiesError(
                f"thing capability definition {definition_file} contains an invalid thing type"
            )
        if not isinstance(raw_capabilities, list):
            raise ThingCapabilitiesError(
                f"thing type {thing_type!r} capabilities must be a JSON array"
            )
        if any(not isinstance(item, str) for item in raw_capabilities):
            raise ThingCapabilitiesError(
                f"thing type {thing_type!r} capabilities must be strings"
            )
        definitions[thing_type] = parse_capabilities_set(
            encode_capabilities_set(raw_capabilities),
            thing_name=f"thing type {thing_type}",
        )
    return definitions


def capabilities_for_thing_type(
    thing_type: str,
    *,
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    definitions = load_thing_type_capabilities(repo_root=repo_root)
    try:
        return definitions[thing_type]
    except KeyError as err:
        raise ThingCapabilitiesError(
            f"thing type {thing_type!r} has no capability definition"
        ) from err
