#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


VERSION_RE = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)$")
RELEASE_MESSAGE_RE = re.compile(r"^chore: release v[0-9]+\.[0-9]+\.[0-9]+ \[skip ci\]$")
BOT_MARKERS = (
    "github-actions[bot]",
    "41898282+github-actions[bot]@users.noreply.github.com",
)


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"version must be plain semantic X.Y.Z, got {value!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def format_version(version: tuple[int, int, int]) -> str:
    return f"{version[0]}.{version[1]}.{version[2]}"


def bump_patch(version: str, count: int) -> str:
    major, minor, patch = parse_version(version)
    if count < 0:
        raise ValueError("count must not be negative")
    return format_version((major, minor, patch + count))


def commit_strings(commit: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("message",):
        value = commit.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("author", "committer"):
        actor = commit.get(key)
        if isinstance(actor, dict):
            for actor_key in ("name", "email", "username", "login"):
                value = actor.get(actor_key)
                if isinstance(value, str):
                    values.append(value)
    return values


def is_release_bot_commit(commit: dict[str, Any]) -> bool:
    message = commit.get("message")
    if isinstance(message, str) and RELEASE_MESSAGE_RE.fullmatch(message.strip()):
        return True
    lowered = [value.lower() for value in commit_strings(commit)]
    return any(marker in value for marker in BOT_MARKERS for value in lowered)


def count_release_commits(event: dict[str, Any]) -> int:
    commits = event.get("commits")
    if not isinstance(commits, list):
        head_commit = event.get("head_commit")
        commits = [head_commit] if isinstance(head_commit, dict) else []
    return sum(
        1
        for commit in commits
        if isinstance(commit, dict) and not is_release_bot_commit(commit)
    )


def plan_release(current_version: str, event: dict[str, Any]) -> dict[str, str]:
    release_commit_count = count_release_commits(event)
    next_version = bump_patch(current_version, release_commit_count)
    should_release = release_commit_count > 0
    return {
        "should_release": "true" if should_release else "false",
        "current_version": current_version,
        "next_version": next_version,
        "tag": f"v{next_version}",
        "commit_count": str(release_commit_count),
    }


def write_outputs(path: Path, outputs: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or apply txing main-branch patch release bumps.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Update VERSION when a release is needed.")
    parser.add_argument("--outputs", type=Path, help="Optional GitHub Actions output file.")
    args = parser.parse_args()

    version_path = args.repo / "VERSION"
    current_version = version_path.read_text(encoding="utf-8").strip()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    outputs = plan_release(current_version, event)

    if args.write and outputs["should_release"] == "true":
        version_path.write_text(f"{outputs['next_version']}\n", encoding="utf-8")

    if args.outputs is not None:
        write_outputs(args.outputs, outputs)
    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
