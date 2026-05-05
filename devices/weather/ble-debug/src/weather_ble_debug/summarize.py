from __future__ import annotations

import argparse
import math
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .cli import format_event
from .protocol import REDCON_ACTIVE, REDCON_IDLE


@dataclass(slots=True)
class LogEvent:
    timestamp: datetime | None
    name: str
    fields: dict[str, str]


@dataclass(slots=True)
class LogSummary:
    path: Path
    failed: bool
    fields: dict[str, object]


def parse_log_line(line: str) -> LogEvent | None:
    try:
        parts = shlex.split(line.strip())
    except ValueError:
        return None
    if len(parts) < 2:
        return None

    try:
        timestamp = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
    except ValueError:
        timestamp = None

    fields: dict[str, str] = {}
    for token in parts[2:]:
        key, separator, value = token.partition("=")
        if not separator:
            continue
        fields[key] = value
    return LogEvent(timestamp=timestamp, name=parts[1], fields=fields)


def summarize_path(path: Path) -> LogSummary:
    events = [
        event
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if (event := parse_log_line(line)) is not None
    ]
    reasons: list[str] = []
    error_stages: list[str] = []
    wake_latencies: list[int] = []
    sleep_latencies: list[int] = []
    active_segments: list[list[datetime]] = []
    active_measurements: list[datetime] = []
    active = False
    slept_after_active = False
    measurement_count = 0
    measurements_after_sleep = 0

    service_adv = any(
        event.name == "adv" and _int_field(event, "service") == 1 for event in events
    )
    unexpected_disconnects = sum(
        1 for event in events if event.name == "disconnect" and _int_field(event, "unexpected") == 1
    )
    service_events = [event for event in events if event.name == "services"]
    commands = {event.fields.get("command") for event in events if event.name == "summary"}
    commands.discard(None)
    needs_services = not commands or commands != {"scan"}

    if not service_adv:
        reasons.append("no-service-adv")
    if unexpected_disconnects:
        reasons.append("unexpected-disconnect")
    if needs_services:
        if not service_events:
            reasons.append("missing-services")
        elif not all(_services_complete(event) for event in service_events):
            reasons.append("incomplete-services")

    for event in events:
        if event.name == "error":
            error_stages.append(event.fields.get("stage", "unknown"))
            reasons.append("cli-error")
        elif event.name == "wake-ok":
            if (latency := _int_field(event, "latencyMs")) is not None:
                wake_latencies.append(latency)
                if latency > 10_000:
                    reasons.append("wake-over-deadline")
        elif event.name == "sleep-ok":
            if (latency := _int_field(event, "latencyMs")) is not None:
                sleep_latencies.append(latency)
        elif event.name == "state":
            redcon = _int_field(event, "redcon")
            if redcon is None:
                continue
            if redcon <= REDCON_ACTIVE:
                if not active:
                    active_measurements = []
                active = True
                slept_after_active = False
            elif redcon >= REDCON_IDLE:
                if active_measurements:
                    active_segments.append(active_measurements)
                active_measurements = []
                slept_after_active = active
                active = False
        elif event.name == "measurement":
            measurement_count += 1
            if active and event.timestamp is not None:
                active_measurements.append(event.timestamp)
            elif slept_after_active:
                measurements_after_sleep += 1

    if active_measurements:
        active_segments.append(active_measurements)

    intervals_ms = _measurement_intervals_ms(active_segments)
    if intervals_ms and (min(intervals_ms) < 650 or max(intervals_ms) > 1350):
        reasons.append("measurement-cadence")
    if measurements_after_sleep:
        reasons.append("measurement-after-sleep")

    unique_reasons = sorted(set(reasons))
    failed = bool(unique_reasons)
    fields: dict[str, object] = {
        "file": str(path),
        "status": "fail" if failed else "pass",
        "reason": ",".join(unique_reasons) if unique_reasons else "-",
        "errorStage": ",".join(sorted(set(error_stages))) if error_stages else "-",
        "unexpectedDisconnects": unexpected_disconnects,
        "measurementCount": measurement_count,
        "measurementsAfterSleep": measurements_after_sleep,
    }
    fields.update(_latency_fields("wake", wake_latencies))
    fields.update(_latency_fields("sleep", sleep_latencies, include_max=False, include_p50=False))
    fields.update(_interval_fields(intervals_ms))
    return LogSummary(path=path, failed=failed, fields=fields)


def _services_complete(event: LogEvent) -> bool:
    return all(
        _int_field(event, key) == 1
        for key in ("command", "state", "measurement")
    )


def _int_field(event: LogEvent, key: str) -> int | None:
    value = event.fields.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _latency_fields(
    prefix: str,
    values: list[int],
    *,
    include_max: bool = True,
    include_p50: bool = True,
) -> dict[str, object]:
    if not values:
        fields: dict[str, object] = {f"{prefix}P95Ms": "-"}
        if include_p50:
            fields[f"{prefix}P50Ms"] = "-"
        if include_max:
            fields[f"{prefix}MaxMs"] = "-"
        return fields

    fields = {f"{prefix}P95Ms": _percentile(values, 0.95)}
    if include_p50:
        fields[f"{prefix}P50Ms"] = _percentile(values, 0.50)
    if include_max:
        fields[f"{prefix}MaxMs"] = max(values)
    return fields


def _percentile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _measurement_intervals_ms(segments: list[list[datetime]]) -> list[int]:
    intervals: list[int] = []
    for segment in segments:
        intervals.extend(
            int(round((right - left).total_seconds() * 1000))
            for left, right in zip(segment, segment[1:])
        )
    return intervals


def _interval_fields(values: list[int]) -> dict[str, object]:
    if not values:
        return {
            "minIntervalMs": "-",
            "avgIntervalMs": "-",
            "maxIntervalMs": "-",
        }
    return {
        "minIntervalMs": min(values),
        "avgIntervalMs": int(round(sum(values) / len(values))),
        "maxIntervalMs": max(values),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weather-ble-debug-summarize")
    parser.add_argument("logs", nargs="+", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failed = False
    for path in args.logs:
        summary = summarize_path(path)
        failed = failed or summary.failed
        print(format_event("summary", **summary.fields))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
