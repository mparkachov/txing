from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from aws.device_catalog import (
    DeviceManifest,
    DeviceManifestError,
    RigProcessContract,
    load_device_manifest,
)


DEVICE_PROCESS_ENVIRONMENT = (
    "TXING_DEVICE_TYPE",
    "TXING_DEVICE_DIR",
    "TXING_DEVICE_MANIFEST",
    "THING_NAME",
    "SPARKPLUG_GROUP_ID",
    "SPARKPLUG_EDGE_NODE_ID",
    "AWS_REGION",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_SELECTED_PROFILE",
)


class DeviceProcessError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class DeviceProcessInvocation:
    device_type: str
    process_name: str
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]


def get_device_process(
    manifest: DeviceManifest,
    process_name: str,
) -> RigProcessContract:
    for process in manifest.rig_processes:
        if process.name == process_name:
            return process
    raise DeviceProcessError(
        f"device type {manifest.type!r} has no rig process {process_name!r}"
    )


def build_device_process_environment(
    manifest: DeviceManifest,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_environment or os.environ)
    env.update(
        {
            "TXING_DEVICE_TYPE": manifest.type,
            "TXING_DEVICE_DIR": str(manifest.device_dir),
            "TXING_DEVICE_MANIFEST": str(manifest.manifest_file),
        }
    )
    return env


def build_device_process_invocation(
    manifest: DeviceManifest,
    process_name: str,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> DeviceProcessInvocation:
    process = get_device_process(manifest, process_name)
    env = build_device_process_environment(
        manifest,
        base_environment=base_environment,
    )
    missing_environment = [
        name
        for name in process.environment
        if name not in env or env[name].strip() == ""
    ]
    if missing_environment:
        raise DeviceProcessError(
            f"rig process {process.name!r} is missing required environment: "
            + ", ".join(missing_environment)
        )
    return DeviceProcessInvocation(
        device_type=manifest.type,
        process_name=process.name,
        argv=process.argv,
        cwd=process.cwd or manifest.device_dir,
        env=env,
    )


def run_device_process(
    manifest: DeviceManifest,
    process_name: str,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> int:
    invocation = build_device_process_invocation(
        manifest,
        process_name,
        base_environment=base_environment,
    )
    completed = subprocess.run(
        invocation.argv,
        cwd=invocation.cwd,
        env=invocation.env,
        check=False,
    )
    return completed.returncode


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-device-process",
        description="Run manifest-declared device rig processes without importing device code.",
    )
    parser.add_argument("--device-type", required=True)
    parser.add_argument(
        "--repo-root",
        default="",
        help="Repository root override for manifest discovery.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List manifest-declared rig processes")
    run_parser = subparsers.add_parser("run", help="Run one manifest-declared process")
    run_parser.add_argument("--process", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    try:
        manifest = load_device_manifest(args.device_type, repo_root=repo_root)
    except DeviceManifestError as err:
        raise SystemExit(str(err)) from err

    if args.command == "list":
        for process in manifest.rig_processes:
            print(process.name)
        return 0

    if args.command == "run":
        return run_device_process(manifest, args.process)

    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
