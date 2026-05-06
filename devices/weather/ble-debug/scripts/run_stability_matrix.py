#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


BLE_DEBUG_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BLE_DEBUG_DIR.parents[2]
SRC_DIR = BLE_DEBUG_DIR / "src"
FIRMWARE_SCRIPT = BLE_DEBUG_DIR / "scripts" / "firmware.py"
DEFAULT_RESULTS_ROOT = Path("/tmp/weather-ble-debug-results")

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from weather_ble_debug.summarize import LogSummary, summarize_path  # noqa: E402


@dataclass(frozen=True, slots=True)
class FirmwareProfile:
    name: str
    idle_interval_ms: int
    idle_latency: int
    supervision_timeout_ms: int
    idle_param_fallback_delay_ms: int
    idle_param_initial_delay_ms: int


@dataclass(slots=True)
class CommandResult:
    label: str
    profile: str
    command: list[str]
    log_path: Path
    exit_code: int
    started_at: str
    duration_sec: float


def load_profiles() -> dict[str, FirmwareProfile]:
    spec = importlib.util.spec_from_file_location("weather_ble_debug_firmware", FIRMWARE_SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit(f"failed to load {FIRMWARE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return {
        name: FirmwareProfile(
            name=profile.name,
            idle_interval_ms=profile.idle_interval_ms,
            idle_latency=profile.idle_latency,
            supervision_timeout_ms=profile.supervision_timeout_ms,
            idle_param_fallback_delay_ms=profile.idle_param_fallback_delay_ms,
            idle_param_initial_delay_ms=profile.idle_param_initial_delay_ms,
        )
        for name, profile in module.PROFILES.items()
    }


PROFILES = load_profiles()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_flash_retry_env(args)
    selected_profiles = validate_profiles(args.profiles)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    results_dir = args.results_root / run_id
    results_dir.mkdir(parents=True, exist_ok=False)
    report_path = results_dir / "analysis-report.md"
    manifest_path = results_dir / "manifest.jsonl"

    write_report_header(report_path, args, selected_profiles, run_id)

    all_results: list[CommandResult] = []
    candidate_summaries: dict[str, list[LogSummary]] = {}
    candidate_failed_commands: dict[str, list[str]] = {}

    for profile in selected_profiles:
        profile_dir = results_dir / profile.name
        profile_dir.mkdir()
        append_report(report_path, f"\n## Candidate `{profile.name}`\n\n")
        append_profile_metadata(report_path, profile)

        flash_result = run_logged(
            label="flash",
            profile=profile.name,
            command=flash_command(args.name, profile.name, args.flash_mode),
            log_path=profile_dir / "flash.log",
            report_path=report_path,
            manifest_path=manifest_path,
            dry_run=args.dry_run,
        )
        all_results.append(flash_result)
        if flash_result.exit_code != 0 and not args.keep_going_after_flash_failure:
            candidate_failed_commands[profile.name] = ["flash"]
            append_report(
                report_path,
                "Flash failed. Stopping before BLE tests for this candidate.\n\n",
            )
            return finalize(report_path, all_results, candidate_summaries)

        if not args.no_verify:
            verify_result = run_logged(
                label="verify",
                profile=profile.name,
                command=verify_command(args.name, profile.name, args.flash_mode),
                log_path=profile_dir / "verify.log",
                report_path=report_path,
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            all_results.append(verify_result)
            if verify_result.exit_code != 0 and not args.keep_going_after_flash_failure:
                candidate_failed_commands[profile.name] = ["verify"]
                append_report(
                    report_path,
                    "Verify failed. Stopping before BLE tests for this candidate.\n\n",
                )
                return finalize(report_path, all_results, candidate_summaries)

        if args.settle_seconds > 0 and not args.dry_run:
            append_report(report_path, f"Settling for {args.settle_seconds:.1f} seconds.\n\n")
            time.sleep(args.settle_seconds)

        test_commands = [
            ("scan", ["just", "weather::ble-debug::scan", args.name, str(args.scan_timeout)]),
            ("inspect", ["just", "weather::ble-debug::inspect", args.name]),
            ("idle-5m", ["just", "weather::ble-debug::idle", args.name, str(args.idle_seconds)]),
            (
                "soak-30m",
                [
                    "just",
                    "weather::ble-debug::soak",
                    args.name,
                    str(args.soak_cycles),
                    str(args.active_seconds),
                    str(args.idle_cycle_seconds),
                    str(args.deadline),
                ],
            ),
        ]

        failed_labels: list[str] = []
        for label, command in test_commands:
            result = run_logged(
                label=label,
                profile=profile.name,
                command=command,
                log_path=profile_dir / f"{label}.log",
                report_path=report_path,
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            all_results.append(result)
            if result.exit_code != 0:
                failed_labels.append(label)
                if args.stop_on_test_failure:
                    break

        candidate_failed_commands[profile.name] = failed_labels
        summaries = summarize_logs(profile_dir, report_path, skip=args.dry_run)
        candidate_summaries[profile.name] = summaries

    confirmation_profiles = pick_confirmation_profiles(
        candidate_summaries,
        candidate_failed_commands,
        selected_profiles,
        args.confirm_top,
    )
    if args.no_confirm:
        confirmation_profiles = []

    if confirmation_profiles:
        append_report(report_path, "\n## Confirmation\n\n")
    for profile in confirmation_profiles:
        profile_dir = results_dir / profile.name
        append_report(report_path, f"\n### `{profile.name}`\n\n")

        if args.flash_before_confirm:
            result = run_logged(
                label="confirm-flash",
                profile=profile.name,
                command=flash_command(args.name, profile.name, args.flash_mode),
                log_path=profile_dir / "confirm-flash.log",
                report_path=report_path,
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            all_results.append(result)
            if result.exit_code != 0 and not args.keep_going_after_flash_failure:
                break
            if args.settle_seconds > 0 and not args.dry_run:
                time.sleep(args.settle_seconds)

        confirmation_commands = [
            (
                "idle-30m-confirm",
                ["just", "weather::ble-debug::idle", args.name, str(args.confirm_idle_seconds)],
            ),
            (
                "soak-2h-confirm",
                [
                    "just",
                    "weather::ble-debug::soak",
                    args.name,
                    str(args.confirm_soak_cycles),
                    str(args.active_seconds),
                    str(args.idle_cycle_seconds),
                    str(args.deadline),
                ],
            ),
        ]
        for label, command in confirmation_commands:
            result = run_logged(
                label=label,
                profile=profile.name,
                command=command,
                log_path=profile_dir / f"{label}.log",
                report_path=report_path,
                manifest_path=manifest_path,
                dry_run=args.dry_run,
            )
            all_results.append(result)
            if result.exit_code != 0 and args.stop_on_test_failure:
                break
        summarize_logs(profile_dir, report_path, pattern="*confirm.log", skip=args.dry_run)

    return finalize(report_path, all_results, candidate_summaries)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weather-ble-debug-stability-matrix",
        description=(
            "Manual-only end-to-end BLE stability runner. This script flashes firmware "
            "profiles and runs the scan/inspect/idle/soak matrix."
        ),
    )
    parser.add_argument("--name", default="weather-q8zbgb")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--profiles", nargs="+", default=list(PROFILES))
    parser.add_argument("--flash-mode", choices=("app", "full"), default="app")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--settle-seconds", type=float, default=5.0)
    parser.add_argument("--scan-timeout", type=int, default=30)
    parser.add_argument("--idle-seconds", type=int, default=300)
    parser.add_argument("--soak-cycles", type=int, default=45)
    parser.add_argument("--active-seconds", type=int, default=20)
    parser.add_argument("--idle-cycle-seconds", type=int, default=20)
    parser.add_argument("--deadline", type=int, default=10)
    parser.add_argument("--confirm-top", type=int, default=2)
    parser.add_argument("--no-confirm", action="store_true")
    parser.add_argument("--confirm-idle-seconds", type=int, default=1800)
    parser.add_argument("--confirm-soak-cycles", type=int, default=180)
    parser.add_argument(
        "--flash-before-confirm",
        dest="flash_before_confirm",
        action="store_true",
        default=True,
    )
    parser.add_argument("--no-flash-before-confirm", dest="flash_before_confirm", action="store_false")
    parser.add_argument("--keep-going-after-flash-failure", action="store_true")
    parser.add_argument("--stop-on-test-failure", action="store_true")
    parser.add_argument(
        "--flash-retries",
        type=int,
        default=None,
        help=(
            "Retries after the first failed flash attempt. Defaults to "
            "WEATHER_BLE_DEBUG_FLASH_RETRIES or 3."
        ),
    )
    parser.add_argument(
        "--flash-retry-delay",
        type=float,
        default=None,
        help=(
            "Seconds to wait between flash retries. Defaults to "
            "WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS or 2."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def configure_flash_retry_env(args: argparse.Namespace) -> None:
    if args.flash_retries is not None:
        if args.flash_retries < 0:
            raise SystemExit("--flash-retries must be non-negative")
        os.environ["WEATHER_BLE_DEBUG_FLASH_RETRIES"] = str(args.flash_retries)
    if args.flash_retry_delay is not None:
        if args.flash_retry_delay < 0:
            raise SystemExit("--flash-retry-delay must be non-negative")
        os.environ["WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS"] = str(args.flash_retry_delay)


def validate_profiles(names: list[str]) -> list[FirmwareProfile]:
    unknown = [name for name in names if name not in PROFILES]
    if unknown:
        raise SystemExit(
            "unknown profile(s): "
            + ", ".join(unknown)
            + "\nknown profiles: "
            + ", ".join(PROFILES)
        )
    return [PROFILES[name] for name in names]


def flash_command(name: str, profile: str, flash_mode: str) -> list[str]:
    if flash_mode == "app":
        return ["just", "weather::ble-debug::firmware-app", profile]
    return [
        "bash",
        "-lc",
        " && ".join(
            (
                "just weather::ble-debug::firmware-softdevice",
                f"just weather::ble-debug::firmware-nve {shlex.quote(name)}",
                f"just weather::ble-debug::firmware-app {shlex.quote(profile)}",
            )
        ),
    ]


def verify_command(name: str, profile: str, flash_mode: str) -> list[str]:
    if flash_mode == "app":
        return ["just", "weather::ble-debug::firmware-verify-app", profile]
    return [
        "bash",
        "-lc",
        " && ".join(
            (
                "just weather::ble-debug::firmware-verify-softdevice",
                f"just weather::ble-debug::firmware-verify-nve {shlex.quote(name)}",
                f"just weather::ble-debug::firmware-verify-app {shlex.quote(profile)}",
            )
        ),
    ]


def run_logged(
    *,
    label: str,
    profile: str,
    command: list[str],
    log_path: Path,
    report_path: Path,
    manifest_path: Path,
    dry_run: bool,
) -> CommandResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    started_text = started.isoformat(timespec="seconds")
    display = shlex.join(command)
    append_report(report_path, f"### `{label}`\n\n```sh\n{display}\n```\n\n")
    if dry_run:
        log_path.write_text(f"DRY RUN: {display}\n", encoding="utf-8")
        result = CommandResult(label, profile, command, log_path, 0, started_text, 0.0)
        append_command_result(report_path, result)
        append_manifest(manifest_path, result)
        return result

    started_monotonic = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"$ {display}\n")
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
            log_file.flush()
        exit_code = process.wait()

    duration = time.monotonic() - started_monotonic
    result = CommandResult(label, profile, command, log_path, exit_code, started_text, duration)
    append_command_result(report_path, result)
    append_result_diagnostics(report_path, result)
    append_manifest(manifest_path, result)
    return result


def append_command_result(report_path: Path, result: CommandResult) -> None:
    append_report(
        report_path,
        (
            f"- exit: `{result.exit_code}`\n"
            f"- duration: `{result.duration_sec:.1f}s`\n"
            f"- log: `{result.log_path}`\n\n"
        ),
    )


def append_manifest(path: Path, result: CommandResult) -> None:
    record = {
        "label": result.label,
        "profile": result.profile,
        "command": result.command,
        "log": str(result.log_path),
        "exitCode": result.exit_code,
        "startedAt": result.started_at,
        "durationSec": round(result.duration_sec, 3),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def summarize_logs(
    profile_dir: Path,
    report_path: Path,
    *,
    pattern: str = "*.log",
    skip: bool = False,
) -> list[LogSummary]:
    if skip:
        append_report(report_path, "Dry run: summaries skipped.\n\n")
        return []

    logs = sorted(
        path
        for path in profile_dir.glob(pattern)
        if path.name not in {"flash.log", "verify.log", "confirm-flash.log"}
    )
    summaries = [summarize_path(path) for path in logs]
    append_report(report_path, "#### Log summaries\n\n```text\n")
    for summary in summaries:
        line = " ".join(f"{key}={value}" for key, value in summary.fields.items())
        append_report(report_path, line + "\n")
    append_report(report_path, "```\n\n")
    append_candidate_diagnosis(report_path, summaries)
    return summaries


def append_result_diagnostics(report_path: Path, result: CommandResult) -> None:
    if result.label not in {"flash", "confirm-flash", "verify"}:
        return
    lines = openocd_diagnostics(result.log_path)
    if not lines:
        return
    append_report(report_path, "#### OpenOCD diagnostics\n\n```text\n")
    for line in lines:
        append_report(report_path, line + "\n")
    append_report(report_path, "```\n\n")


def openocd_diagnostics(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    attempts = re.findall(r"^flash attempt (\d+)/(\d+) label=(\S+)", text, re.MULTILINE)
    retries = re.findall(
        r"^flash retry (\d+)/(\d+) label=(\S+) exit=(\d+) nextDelaySec=([0-9.]+)",
        text,
        re.MULTILINE,
    )
    successes = re.findall(r"^flash succeeded label=(\S+) attempts=(\d+)", text, re.MULTILINE)
    failed_addresses = re.findall(r"Failed to write memory at (0x[0-9a-fA-F]+)", text)
    access_errors = re.findall(r"RRAMC ACCESSERRORADDR:\s*(0x[0-9a-fA-F]+)", text)
    configs = re.findall(r"RRAMC CONFIG:\s*(0x[0-9a-fA-F]+)", text)
    bufstatuses = re.findall(r"RRAMC BUFSTATUS:\s*(0x[0-9a-fA-F]+)", text)
    writes = re.findall(r"(\d+) bytes written at address (0x[0-9a-fA-F]+)", text)
    verified = re.findall(r"verified (\d+) bytes in ([0-9.]+)s", text)
    openocd_errors = re.findall(r"^Error: (.+)$", text, re.MULTILINE)

    if not any(
        (attempts, retries, successes, failed_addresses, access_errors, writes, verified, openocd_errors)
    ):
        return []

    lines: list[str] = []
    if attempts:
        last_attempt = attempts[-1]
        lines.append(
            f"flashAttemptsObserved={last_attempt[0]}/{last_attempt[1]} "
            f"labels={','.join(sorted({attempt[2] for attempt in attempts}))}"
        )
    if retries:
        retry_parts = [
            f"{retry[2]}:{retry[0]}/{retry[1]}:exit{retry[3]}:delay{retry[4]}s"
            for retry in retries
        ]
        lines.append(f"flashRetries={';'.join(retry_parts)}")
    if successes:
        success_parts = [f"{label}:attempts{count}" for label, count in successes]
        lines.append(f"flashSuccess={';'.join(success_parts)}")
    if failed_addresses:
        lines.append(
            f"failedWriteCount={len(failed_addresses)} "
            f"addresses={','.join(failed_addresses)}"
        )
    if access_errors or configs or bufstatuses:
        lines.append(
            "rramc "
            f"accessError={last_or_dash(access_errors)} "
            f"config={last_or_dash(configs)} "
            f"bufStatus={last_or_dash(bufstatuses)}"
        )
    if writes:
        total_written = sum(int(size) for size, _address in writes)
        last_writes = ",".join(f"{size}@{address}" for size, address in writes[-4:])
        lines.append(
            f"writeSegments={len(writes)} totalBytes={total_written} lastSegments={last_writes}"
        )
    if verified:
        verify_parts = [f"{size}B/{seconds}s" for size, seconds in verified]
        lines.append(f"verifySegments={len(verified)} details={';'.join(verify_parts)}")
    if openocd_errors:
        lines.append(f"openocdErrors={';'.join(openocd_errors[-3:])}")
    return lines


def last_or_dash(values: list[str]) -> str:
    return values[-1] if values else "-"


def append_candidate_diagnosis(report_path: Path, summaries: list[LogSummary]) -> None:
    if not summaries:
        return
    reasons = [str(summary.fields.get("reason", "")) for summary in summaries]
    error_stages = {str(summary.fields.get("errorStage", "-")) for summary in summaries}
    if all("no-service-adv" in reason for reason in reasons):
        append_report(
            report_path,
            (
                "#### Candidate diagnosis\n\n"
                "No required service advertisement was observed after flash/verify. "
                "This blocks service discovery and means the next failure to debug is "
                "firmware boot, factory-name loading, or advertising setup, before BLE "
                "connection stability can be ranked.\n\n"
            ),
        )
    elif any("discover" in stage for stage in error_stages):
        append_report(
            report_path,
            (
                "#### Candidate diagnosis\n\n"
                "At least one command failed during BLE discovery. Inspect the scan and "
                "inspect logs before interpreting wake or soak timing.\n\n"
            ),
        )


def pick_confirmation_profiles(
    summaries: dict[str, list[LogSummary]],
    failed_commands: dict[str, list[str]],
    selected_profiles: list[FirmwareProfile],
    count: int,
) -> list[FirmwareProfile]:
    if count <= 0:
        return []
    profile_by_name = {profile.name: profile for profile in selected_profiles}
    candidates = [
        profile
        for profile in selected_profiles
        if not failed_commands.get(profile.name)
        and summaries.get(profile.name)
        and all(not summary.failed for summary in summaries[profile.name])
    ]
    candidates.sort(key=lambda profile: ranking_key(profile, summaries[profile.name]))
    return [profile_by_name[profile.name] for profile in candidates[:count]]


def ranking_key(profile: FirmwareProfile, summaries: list[LogSummary]) -> tuple[object, ...]:
    wake_p95 = min_int_field(summaries, "wakeP95Ms", default=999_999)
    max_interval = max_int_field(summaries, "maxIntervalMs", default=999_999)
    min_interval = min_int_field(summaries, "minIntervalMs", default=999_999)
    jitter = max(abs(max_interval - 1000), abs(min_interval - 1000))
    return (
        -profile.supervision_timeout_ms,
        wake_p95,
        jitter,
        profile.idle_interval_ms,
    )


def min_int_field(summaries: list[LogSummary], key: str, *, default: int) -> int:
    values = int_fields(summaries, key)
    return min(values) if values else default


def max_int_field(summaries: list[LogSummary], key: str, *, default: int) -> int:
    values = int_fields(summaries, key)
    return max(values) if values else default


def int_fields(summaries: list[LogSummary], key: str) -> list[int]:
    values: list[int] = []
    for summary in summaries:
        value = summary.fields.get(key)
        if isinstance(value, int):
            values.append(value)
        elif isinstance(value, str) and value.isdigit():
            values.append(int(value))
    return values


def finalize(
    report_path: Path,
    results: list[CommandResult],
    summaries: dict[str, list[LogSummary]],
) -> int:
    failed_commands = [result for result in results if result.exit_code != 0]
    failed_summaries = [
        (profile, summary)
        for profile, profile_summaries in summaries.items()
        for summary in profile_summaries
        if summary.failed
    ]
    append_report(report_path, "\n## Final Status\n\n")
    append_report(report_path, f"- command failures: `{len(failed_commands)}`\n")
    append_report(report_path, f"- summary failures: `{len(failed_summaries)}`\n")
    append_report(report_path, f"- report: `{report_path}`\n")
    append_report(report_path, f"- manifest: `{report_path.parent / 'manifest.jsonl'}`\n")
    print(f"\nAnalysis report: {report_path}")
    print(f"Raw logs: {report_path.parent}")
    return 1 if failed_commands or failed_summaries else 0


def write_report_header(
    report_path: Path,
    args: argparse.Namespace,
    profiles: list[FirmwareProfile],
    run_id: str,
) -> None:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    profile_names = ", ".join(profile.name for profile in profiles)
    report_path.write_text(
        "\n".join(
            (
                "# Weather BLE Debug Stability Matrix",
                "",
                f"- run id: `{run_id}`",
                f"- started: `{started}`",
                f"- repo: `{PROJECT_ROOT}`",
                f"- thing name: `{args.name}`",
                f"- profiles: `{profile_names}`",
                f"- flash mode: `{args.flash_mode}`",
                f"- dry run: `{int(args.dry_run)}`",
                f"- scan timeout: `{args.scan_timeout}s`",
                f"- idle screen: `{args.idle_seconds}s`",
                f"- soak screen: `{args.soak_cycles}` cycles",
                f"- confirmation: `{0 if args.no_confirm else args.confirm_top}` top candidates",
                (
                    "- flash retries: `"
                    f"{os.environ.get('WEATHER_BLE_DEBUG_FLASH_RETRIES', '3')}`"
                ),
                (
                    "- flash retry delay: `"
                    f"{os.environ.get('WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS', '2')}s`"
                ),
                "",
            )
        ),
        encoding="utf-8",
    )


def append_profile_metadata(report_path: Path, profile: FirmwareProfile) -> None:
    append_report(
        report_path,
        (
            f"- interval: `{profile.idle_interval_ms} ms`\n"
            f"- latency: `{profile.idle_latency}`\n"
            f"- supervision: `{profile.supervision_timeout_ms} ms`\n"
            f"- fallback delay: `{profile.idle_param_fallback_delay_ms} ms`\n"
            f"- initial delay: `{profile.idle_param_initial_delay_ms} ms`\n\n"
        ),
    )


def append_report(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


if __name__ == "__main__":
    raise SystemExit(main())
