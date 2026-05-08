from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shlex
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .cycle_test import (
    CONNECTION_PROFILES,
    EVENT_SINKS,
    CycleError,
    emit,
    run as run_cycle_test,
)


DEFAULT_NAME = "weather-q8zbgb"
DEFAULT_OUTPUT_ROOT = Path("/tmp/ble-debug-overnight-results")


@dataclass(frozen=True)
class CentralProfile:
    name: str
    scan_timeout: float
    connect_timeout: float
    connect_attempts: int
    retry_delay: float
    disconnect_deadline: float
    require_service: bool


@dataclass(frozen=True)
class Candidate:
    name: str
    conn_profile: str
    central_profile: CentralProfile
    order: int


@dataclass
class TrialCapture:
    passed_cycles: int = 0
    errors: int = 0
    unexpected_disconnects: int = 0
    wake_latencies_ms: list[int] = field(default_factory=list)
    connect_ms: list[int] = field(default_factory=list)

    def __call__(self, line: str) -> None:
        event, fields = parse_event_line(line)
        if event == "summary" and fields.get("command") == "cycle":
            self.passed_cycles += 1
        elif event == "wake-ok":
            append_int(self.wake_latencies_ms, fields.get("latencyMs"))
        elif event == "connected":
            append_int(self.connect_ms, fields.get("connectMs"))
        elif event == "disconnect" and fields.get("unexpected") == "1":
            self.unexpected_disconnects += 1
        elif event == "error":
            self.errors += 1


@dataclass
class TrialResult:
    candidate: str
    conn_profile: str
    central_profile: str
    requested_cycles: int
    passed_cycles: int
    errors: int
    unexpected_disconnects: int
    wake_latencies_ms: list[int]
    connect_ms: list[int]
    success: bool
    error_stage: str = ""
    error_message: str = ""
    elapsed_sec: float = 0.0


@dataclass
class CandidateStats:
    candidate: Candidate
    trials: int = 0
    successful_trials: int = 0
    failed_trials: int = 0
    requested_cycles: int = 0
    passed_cycles: int = 0
    errors: int = 0
    unexpected_disconnects: int = 0
    wake_latencies_ms: list[int] = field(default_factory=list)
    connect_ms: list[int] = field(default_factory=list)

    def record(self, result: TrialResult) -> None:
        self.trials += 1
        self.requested_cycles += result.requested_cycles
        self.passed_cycles += result.passed_cycles
        self.errors += result.errors
        self.unexpected_disconnects += result.unexpected_disconnects
        self.wake_latencies_ms.extend(result.wake_latencies_ms)
        self.connect_ms.extend(result.connect_ms)
        if result.success:
            self.successful_trials += 1
        else:
            self.failed_trials += 1

    @property
    def failure_count(self) -> int:
        return self.failed_trials + self.errors + self.unexpected_disconnects

    @property
    def wake_p95_ms(self) -> int:
        return percentile(self.wake_latencies_ms, 95, default=999999)

    @property
    def connect_p95_ms(self) -> int:
        return percentile(self.connect_ms, 95, default=999999)

    def rank_key(self) -> tuple[float, float, int, int, int, int]:
        trials = max(1, self.trials)
        failure_rate = self.failure_count / trials
        disconnect_rate = self.unexpected_disconnects / trials
        return (
            failure_rate,
            disconnect_rate,
            -self.passed_cycles,
            self.wake_p95_ms,
            self.connect_p95_ms,
            self.candidate.order,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.name,
            "connProfile": self.candidate.conn_profile,
            "centralProfile": self.candidate.central_profile.name,
            "trials": self.trials,
            "successfulTrials": self.successful_trials,
            "failedTrials": self.failed_trials,
            "requestedCycles": self.requested_cycles,
            "passedCycles": self.passed_cycles,
            "errors": self.errors,
            "unexpectedDisconnects": self.unexpected_disconnects,
            "wakeP95Ms": self.wake_p95_ms if self.wake_latencies_ms else None,
            "wakeMaxMs": max(self.wake_latencies_ms) if self.wake_latencies_ms else None,
            "connectP95Ms": self.connect_p95_ms if self.connect_ms else None,
            "connectMaxMs": max(self.connect_ms) if self.connect_ms else None,
        }


class FileSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = path.open("a", encoding="utf-8")

    def __call__(self, line: str) -> None:
        self.handle.write(line + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def parse_event_line(line: str) -> tuple[str, dict[str, str]]:
    try:
        parts = shlex.split(line)
    except ValueError:
        return "", {}
    if len(parts) < 2:
        return "", {}
    fields: dict[str, str] = {}
    for token in parts[2:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return parts[1], fields


def append_int(values: list[int], raw_value: str | None) -> None:
    if raw_value is None:
        return
    try:
        values.append(int(raw_value))
    except ValueError:
        return


def percentile(values: list[int], pct: int, *, default: int) -> int:
    if not values:
        return default
    ordered = sorted(values)
    index = int(round(((pct / 100) * (len(ordered) - 1))))
    return ordered[max(0, min(index, len(ordered) - 1))]


def timestamp_for_path() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def default_central_profiles() -> list[CentralProfile]:
    return [
        CentralProfile(
            name="bluez-conservative-name",
            scan_timeout=120.0,
            connect_timeout=60.0,
            connect_attempts=5,
            retry_delay=5.0,
            disconnect_deadline=10.0,
            require_service=False,
        ),
        CentralProfile(
            name="bluez-conservative-service",
            scan_timeout=120.0,
            connect_timeout=60.0,
            connect_attempts=5,
            retry_delay=5.0,
            disconnect_deadline=10.0,
            require_service=True,
        ),
        CentralProfile(
            name="bluez-balanced-name",
            scan_timeout=90.0,
            connect_timeout=45.0,
            connect_attempts=4,
            retry_delay=3.0,
            disconnect_deadline=10.0,
            require_service=False,
        ),
        CentralProfile(
            name="bluez-balanced-service",
            scan_timeout=90.0,
            connect_timeout=45.0,
            connect_attempts=4,
            retry_delay=3.0,
            disconnect_deadline=10.0,
            require_service=True,
        ),
        CentralProfile(
            name="bluez-fast-service",
            scan_timeout=60.0,
            connect_timeout=30.0,
            connect_attempts=3,
            retry_delay=2.0,
            disconnect_deadline=5.0,
            require_service=True,
        ),
    ]


def default_connection_profiles() -> list[str]:
    return [
        "stable-200-0-20",
        "slow-500-0-20",
        "stable-100-0-20",
        "fast-50-0-20",
        "stable-200-0-10",
        "stable-100-0-10",
        "fast-50-0-10",
        "central-default",
    ]


def parse_csv(value: str | None, defaults: list[str]) -> list[str]:
    if not value:
        return defaults
    parsed = [part.strip() for part in value.split(",") if part.strip()]
    return parsed or defaults


def build_candidates(args: argparse.Namespace) -> list[Candidate]:
    connection_profiles = parse_csv(args.connection_profiles, default_connection_profiles())
    unknown = [name for name in connection_profiles if name not in CONNECTION_PROFILES]
    if unknown:
        raise CycleError(
            "args",
            "unknown connection profile(s): "
            + ", ".join(unknown)
            + ". Options: "
            + ", ".join(sorted(CONNECTION_PROFILES)),
        )

    central_profiles = default_central_profiles()
    requested_central_names = parse_csv(
        args.central_profiles,
        [profile.name for profile in central_profiles],
    )
    central_by_name = {profile.name: profile for profile in central_profiles}
    unknown_central = [name for name in requested_central_names if name not in central_by_name]
    if unknown_central:
        raise CycleError(
            "args",
            "unknown central profile(s): "
            + ", ".join(unknown_central)
            + ". Options: "
            + ", ".join(sorted(central_by_name)),
        )

    candidates: list[Candidate] = []
    order = 0
    for conn_profile in connection_profiles:
        for central_name in requested_central_names:
            central_profile = central_by_name[central_name]
            candidates.append(
                Candidate(
                    name=f"{conn_profile}+{central_profile.name}",
                    conn_profile=conn_profile,
                    central_profile=central_profile,
                    order=order,
                )
            )
            order += 1
    return candidates


def cycle_args_for_candidate(
    args: argparse.Namespace,
    candidate: Candidate,
    cycles: int,
) -> argparse.Namespace:
    central = candidate.central_profile
    return SimpleNamespace(
        repetitions=cycles,
        name=args.name,
        wake_seconds=args.wake_seconds,
        cycle_seconds=args.cycle_seconds,
        min_battery=args.min_battery,
        wake_deadline=args.wake_deadline,
        sleep_deadline=args.sleep_deadline,
        scan_timeout=central.scan_timeout,
        connect_timeout=central.connect_timeout,
        connect_attempts=central.connect_attempts,
        retry_delay=central.retry_delay,
        disconnect_deadline=central.disconnect_deadline,
        keep_connected_during_sleep=False,
        require_service=central.require_service,
        conn_profile=[candidate.conn_profile],
        conn_params=[],
        conn_profile_cycles=1,
    )


async def run_trial(
    args: argparse.Namespace,
    candidate: Candidate,
    cycles: int,
    *,
    phase: str,
) -> TrialResult:
    capture = TrialCapture()
    started = time.monotonic()
    EVENT_SINKS.append(capture)
    success = False
    error_stage = ""
    error_message = ""
    try:
        emit(
            "trial-start",
            phase=phase,
            candidate=candidate.name,
            connProfile=candidate.conn_profile,
            centralProfile=candidate.central_profile.name,
            cycles=cycles,
            scanTimeout=candidate.central_profile.scan_timeout,
            connectTimeout=candidate.central_profile.connect_timeout,
            connectAttempts=candidate.central_profile.connect_attempts,
            retryDelay=candidate.central_profile.retry_delay,
            disconnectDeadline=candidate.central_profile.disconnect_deadline,
            requireService=int(candidate.central_profile.require_service),
        )
        await run_cycle_test(cycle_args_for_candidate(args, candidate, cycles))
        success = True
    except CycleError as exc:
        error_stage = exc.stage
        error_message = str(exc)
        emit("error", stage=exc.stage, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - overnight runner must keep going.
        error_stage = "unexpected"
        error_message = str(exc) or exc.__class__.__name__
        emit("error", stage=error_stage, message=error_message)
    finally:
        if capture in EVENT_SINKS:
            EVENT_SINKS.remove(capture)

    result = TrialResult(
        candidate=candidate.name,
        conn_profile=candidate.conn_profile,
        central_profile=candidate.central_profile.name,
        requested_cycles=cycles,
        passed_cycles=capture.passed_cycles,
        errors=capture.errors,
        unexpected_disconnects=capture.unexpected_disconnects,
        wake_latencies_ms=list(capture.wake_latencies_ms),
        connect_ms=list(capture.connect_ms),
        success=success,
        error_stage=error_stage,
        error_message=error_message,
        elapsed_sec=time.monotonic() - started,
    )
    emit(
        "trial-summary",
        phase=phase,
        candidate=candidate.name,
        connProfile=candidate.conn_profile,
        centralProfile=candidate.central_profile.name,
        success=int(success),
        requestedCycles=cycles,
        passedCycles=result.passed_cycles,
        errors=result.errors,
        unexpectedDisconnects=result.unexpected_disconnects,
        wakeP95Ms=percentile(result.wake_latencies_ms, 95, default=0),
        connectP95Ms=percentile(result.connect_ms, 95, default=0),
        elapsedSec=int(result.elapsed_sec),
        errorStage=error_stage,
        message=error_message,
    )
    return result


def choose_best(stats_by_candidate: dict[str, CandidateStats]) -> CandidateStats | None:
    populated = [stats for stats in stats_by_candidate.values() if stats.trials > 0]
    if not populated:
        return None
    return min(populated, key=lambda stats: stats.rank_key())


def write_summary(
    output_dir: Path,
    *,
    args: argparse.Namespace,
    candidates: list[Candidate],
    stats_by_candidate: dict[str, CandidateStats],
    best: CandidateStats | None,
    phase: str,
) -> None:
    summary = {
        "phase": phase,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {
            "system": platform.system().lower(),
            "release": platform.release(),
        },
        "args": {
            "name": args.name,
            "durationHours": args.duration_hours,
            "matrixHours": args.matrix_hours,
            "confirmHours": args.confirm_hours,
            "trialCycles": args.trial_cycles,
            "wakeSeconds": args.wake_seconds,
            "cycleSeconds": args.cycle_seconds,
            "minBattery": args.min_battery,
            "wakeDeadline": args.wake_deadline,
            "sleepDeadline": args.sleep_deadline,
        },
        "candidates": [
            {
                "name": candidate.name,
                "connProfile": candidate.conn_profile,
                "centralProfile": asdict(candidate.central_profile),
            }
            for candidate in candidates
        ],
        "best": best.to_dict() if best is not None else None,
        "stats": [stats.to_dict() for stats in sorted(stats_by_candidate.values(), key=lambda s: s.rank_key())],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_report(
    output_dir: Path,
    *,
    best: CandidateStats | None,
    stats_by_candidate: dict[str, CandidateStats],
) -> None:
    lines = [
        "# BLE Debug Overnight Report",
        "",
        f"- Log: `{output_dir / 'overnight.log'}`",
        f"- Summary JSON: `{output_dir / 'summary.json'}`",
        "",
    ]
    if best is None:
        lines.extend(["No candidate completed a trial.", ""])
    else:
        lines.extend(
            [
                "## Selected Candidate",
                "",
                f"- Candidate: `{best.candidate.name}`",
                f"- Connection profile: `{best.candidate.conn_profile}`",
                f"- Central profile: `{best.candidate.central_profile.name}`",
                f"- Passed cycles: `{best.passed_cycles}`",
                f"- Failed trials: `{best.failed_trials}`",
                f"- Unexpected disconnects: `{best.unexpected_disconnects}`",
                f"- Wake p95 ms: `{best.wake_p95_ms if best.wake_latencies_ms else 'n/a'}`",
                f"- Connect p95 ms: `{best.connect_p95_ms if best.connect_ms else 'n/a'}`",
                "",
            ]
        )

    lines.extend(["## Ranked Candidates", ""])
    lines.append(
        "| Candidate | Trials | Passed cycles | Failed trials | Errors | Unexpected disconnects | Wake p95 | Connect p95 |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for stats in sorted(stats_by_candidate.values(), key=lambda item: item.rank_key()):
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{stats.candidate.name}`",
                    str(stats.trials),
                    str(stats.passed_cycles),
                    str(stats.failed_trials),
                    str(stats.errors),
                    str(stats.unexpected_disconnects),
                    str(stats.wake_p95_ms if stats.wake_latencies_ms else "n/a"),
                    str(stats.connect_p95_ms if stats.connect_ms else "n/a"),
                ]
            )
            + " |"
        )
    lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def run_overnight(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / timestamp_for_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    sink = FileSink(output_dir / "overnight.log")
    EVENT_SINKS.append(sink)

    stats_by_candidate: dict[str, CandidateStats] = {}
    candidates: list[Candidate] = []
    best: CandidateStats | None = None
    try:
        candidates = build_candidates(args)
        stats_by_candidate = {
            candidate.name: CandidateStats(candidate=candidate)
            for candidate in candidates
        }
        emit(
            "starting",
            command="overnight",
            name=args.name,
            outputDir=output_dir,
            durationHours=args.duration_hours,
            matrixHours=args.matrix_hours,
            confirmHours=args.confirm_hours,
            trialCycles=args.trial_cycles,
            candidates=len(candidates),
        )
        for candidate in candidates:
            emit(
                "matrix-candidate",
                candidate=candidate.name,
                connProfile=candidate.conn_profile,
                centralProfile=candidate.central_profile.name,
                scanTimeout=candidate.central_profile.scan_timeout,
                connectTimeout=candidate.central_profile.connect_timeout,
                connectAttempts=candidate.central_profile.connect_attempts,
                retryDelay=candidate.central_profile.retry_delay,
                disconnectDeadline=candidate.central_profile.disconnect_deadline,
                requireService=int(candidate.central_profile.require_service),
            )

        if args.dry_run:
            write_summary(
                output_dir,
                args=args,
                candidates=candidates,
                stats_by_candidate=stats_by_candidate,
                best=None,
                phase="dry-run",
            )
            write_report(output_dir, best=None, stats_by_candidate=stats_by_candidate)
            emit("summary", command="overnight", phase="dry-run", outputDir=output_dir)
            return 0

        started = time.monotonic()
        total_seconds = max(args.cycle_seconds, args.duration_hours * 3600.0)
        matrix_seconds = min(args.matrix_hours * 3600.0, max(0.0, total_seconds - args.confirm_hours * 3600.0))
        matrix_deadline = started + matrix_seconds
        overall_deadline = started + total_seconds

        candidate_index = 0
        while (
            time.monotonic() + args.trial_cycles * args.cycle_seconds <= matrix_deadline
            and candidates
        ):
            candidate = candidates[candidate_index % len(candidates)]
            result = await run_trial(args, candidate, args.trial_cycles, phase="matrix")
            stats_by_candidate[candidate.name].record(result)
            best = choose_best(stats_by_candidate)
            write_summary(
                output_dir,
                args=args,
                candidates=candidates,
                stats_by_candidate=stats_by_candidate,
                best=best,
                phase="matrix",
            )
            write_report(output_dir, best=best, stats_by_candidate=stats_by_candidate)
            candidate_index += 1

        best = choose_best(stats_by_candidate)
        if best is None:
            fallback = candidates[0]
            best = stats_by_candidate[fallback.name]
            emit(
                "confirm-selected",
                candidate=fallback.name,
                reason="fallback-no-successful-matrix-candidate",
            )
        else:
            emit(
                "confirm-selected",
                candidate=best.candidate.name,
                connProfile=best.candidate.conn_profile,
                centralProfile=best.candidate.central_profile.name,
                passedCycles=best.passed_cycles,
                failedTrials=best.failed_trials,
                unexpectedDisconnects=best.unexpected_disconnects,
                wakeP95Ms=best.wake_p95_ms if best.wake_latencies_ms else 0,
                connectP95Ms=best.connect_p95_ms if best.connect_ms else 0,
            )

        remaining_seconds = max(0.0, overall_deadline - time.monotonic())
        confirm_cycles = int(remaining_seconds // args.cycle_seconds)
        if confirm_cycles > 0 and best is not None:
            result = await run_trial(args, best.candidate, confirm_cycles, phase="confirm")
            stats_by_candidate[best.candidate.name].record(result)
            best = choose_best(stats_by_candidate)

        write_summary(
            output_dir,
            args=args,
            candidates=candidates,
            stats_by_candidate=stats_by_candidate,
            best=best,
            phase="complete",
        )
        write_report(output_dir, best=best, stats_by_candidate=stats_by_candidate)
        emit(
            "summary",
            command="overnight",
            outputDir=output_dir,
            report=output_dir / "report.md",
            summaryJson=output_dir / "summary.json",
            best=best.candidate.name if best is not None else "",
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - leave an analysis file instead of a traceback.
        emit("error", stage="overnight", message=str(exc) or exc.__class__.__name__)
        write_summary(
            output_dir,
            args=args,
            candidates=candidates,
            stats_by_candidate=stats_by_candidate,
            best=best,
            phase="failed",
        )
        write_report(output_dir, best=best, stats_by_candidate=stats_by_candidate)
        emit(
            "summary",
            command="overnight",
            outputDir=output_dir,
            report=output_dir / "report.md",
            summaryJson=output_dir / "summary.json",
            failed=1,
        )
        return 0
    finally:
        if sink in EVENT_SINKS:
            EVENT_SINKS.remove(sink)
        sink.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an overnight BLE parameter matrix. The default target is eight "
            "hours: seven hours of matrix trials followed by one hour confirming "
            "the best observed candidate."
        )
    )
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--output-dir", help="result directory; default is /tmp/ble-debug-overnight-results/<timestamp>")
    parser.add_argument("--duration-hours", type=float, default=8.0)
    parser.add_argument("--matrix-hours", type=float, default=7.0)
    parser.add_argument("--confirm-hours", type=float, default=1.0)
    parser.add_argument("--trial-cycles", type=int, default=5)
    parser.add_argument("--wake-seconds", type=float, default=30.0)
    parser.add_argument("--cycle-seconds", type=float, default=60.0)
    parser.add_argument("--min-battery", type=int, default=3)
    parser.add_argument("--wake-deadline", type=float, default=10.0)
    parser.add_argument("--sleep-deadline", type=float, default=10.0)
    parser.add_argument(
        "--connection-profiles",
        help="comma-separated subset of built-in connection profiles for the matrix",
    )
    parser.add_argument(
        "--central-profiles",
        help="comma-separated subset of built-in BlueZ-side scan/connect profiles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write matrix files without touching BLE hardware",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run_overnight(args)))
    except KeyboardInterrupt:
        emit("error", stage="signal", message="interrupted")
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001 - do not leave overnight runs with traceback only.
        emit("error", stage="overnight", message=str(exc) or exc.__class__.__name__)
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
