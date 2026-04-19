from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .auth import AwsRuntime, build_aws_runtime, ensure_aws_profile


_SCOPE_LABELS = {
    "rig": "rig",
    "device": "device",
    "txing": "device",
}
_SCOPE_PROFILE_ENV_NAMES = {
    "rig": ("AWS_PROFILE", "AWS_RIG_PROFILE"),
    "device": ("AWS_PROFILE", "AWS_DEVICE_PROFILE", "AWS_TXING_PROFILE"),
    "txing": ("AWS_PROFILE", "AWS_TXING_PROFILE"),
}


@dataclass(slots=True, frozen=True)
class CheckResult:
    ok: bool
    message: str


def _ok(message: str) -> CheckResult:
    return CheckResult(ok=True, message=message)


def _fail(message: str) -> CheckResult:
    return CheckResult(ok=False, message=message)


def _format_env_names(names: Sequence[str]) -> str:
    return " or ".join(f"${name}" for name in names)


def _first_non_empty(environment: Mapping[str, str], *names: str) -> tuple[str | None, str | None]:
    for name in names:
        value = environment.get(name, "").strip()
        if value:
            return name, value
    return None, None


def _check_text_env(
    environment: Mapping[str, str],
    label: str,
    *names: str,
) -> tuple[CheckResult, str | None]:
    env_name, value = _first_non_empty(environment, *names)
    if value is None:
        return _fail(f"{label} missing ({_format_env_names(names)})"), None
    return _ok(f"{label} ({env_name})"), value


def _check_file_env(
    environment: Mapping[str, str],
    label: str,
    *names: str,
) -> tuple[CheckResult, Path | None]:
    result, value = _check_text_env(environment, label, *names)
    if value is None:
        return result, None
    path = Path(value)
    if path.is_file():
        return _ok(f"{label} ({path})"), path
    return _fail(f"{label} missing or not a file ({path})"), None


def _validate_common_environment(
    environment: Mapping[str, str],
    *,
    profile_env_names: Sequence[str],
    require_thing_name: bool,
) -> tuple[list[CheckResult], dict[str, Any]]:
    results: list[CheckResult] = []
    resolved: dict[str, Any] = {}

    result, region_name = _check_text_env(
        environment,
        "AWS region",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    )
    results.append(result)
    if region_name is not None:
        resolved["aws_region"] = region_name

    result, _profile_name = _check_text_env(
        environment,
        "AWS runtime profile selector",
        *profile_env_names,
    )
    results.append(result)

    result, shared_credentials_file = _check_file_env(
        environment,
        "AWS shared credentials file",
        "AWS_SHARED_CREDENTIALS_FILE",
    )
    results.append(result)
    if shared_credentials_file is not None:
        resolved["aws_shared_credentials_file"] = shared_credentials_file

    result, aws_config_file = _check_file_env(
        environment,
        "AWS config file",
        "AWS_CONFIG_FILE",
    )
    results.append(result)
    if aws_config_file is not None:
        resolved["aws_config_file"] = aws_config_file

    if require_thing_name:
        result, thing_name = _check_text_env(environment, "Thing name", "THING_NAME")
        results.append(result)
        if thing_name is not None:
            resolved["thing_name"] = thing_name

    return results, resolved


def validate_service_environment(
    scope: str,
    environment: Mapping[str, str],
) -> tuple[list[CheckResult], dict[str, Any]]:
    if scope not in _SCOPE_LABELS:
        raise ValueError(f"unsupported scope: {scope}")

    results, resolved = _validate_common_environment(
        environment,
        profile_env_names=_SCOPE_PROFILE_ENV_NAMES[scope],
        require_thing_name=(scope != "rig"),
    )

    if scope == "rig":
        for key, label, env_name in (
            ("rig_name", "Rig name", "RIG_NAME"),
            ("sparkplug_group_id", "Sparkplug group ID", "SPARKPLUG_GROUP_ID"),
            ("sparkplug_edge_node_id", "Sparkplug edge node ID", "SPARKPLUG_EDGE_NODE_ID"),
            ("log_group_name", "CloudWatch log group", "CLOUDWATCH_LOG_GROUP"),
        ):
            result, value = _check_text_env(environment, label, env_name)
            results.append(result)
            if value is not None:
                resolved[key] = value
        return results, resolved

    result, schema_file = _check_file_env(environment, "Shadow schema file", "SCHEMA_FILE")
    results.append(result)
    if schema_file is not None:
        resolved["schema_file"] = schema_file

    for key, label, env_name in (
        ("video_viewer_url", "Board video viewer URL", "BOARD_VIDEO_VIEWER_URL"),
        ("video_region", "Board video region", "BOARD_VIDEO_REGION"),
        ("video_channel_name", "Board video channel name", "BOARD_VIDEO_CHANNEL_NAME"),
        ("video_sender_command", "Board video sender command", "BOARD_VIDEO_SENDER_COMMAND"),
    ):
        result, value = _check_text_env(environment, label, env_name)
        results.append(result)
        if value is not None:
            resolved[key] = value
    return results, resolved


def _format_exception(err: Exception) -> str:
    response = getattr(err, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            code = error.get("Code")
            message = error.get("Message")
            if code and message:
                return f"{code}: {message}"
            if code:
                return str(code)
    return str(err) or err.__class__.__name__


def _run_aws_check(
    results: list[CheckResult],
    label: str,
    operation: Any,
) -> Any:
    try:
        value = operation()
    except Exception as err:
        results.append(_fail(f"{label} ({_format_exception(err)})"))
        return None
    results.append(_ok(label))
    return value


def _build_runtime(scope: str, *, region_name: str) -> AwsRuntime:
    if scope == "rig":
        ensure_aws_profile("AWS_RIG_PROFILE")
    elif scope == "device":
        ensure_aws_profile("AWS_DEVICE_PROFILE", "AWS_TXING_PROFILE")
    else:
        ensure_aws_profile("AWS_TXING_PROFILE")
    return build_aws_runtime(region_name=region_name)


def _probe_cloudwatch_logs(
    runtime: AwsRuntime,
    *,
    log_group_name: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    logs_client = runtime.logs_client()
    stream_name = (
        f"aws-check-"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{os.getpid()}"
    )

    try:
        logs_client.create_log_stream(
            logGroupName=log_group_name,
            logStreamName=stream_name,
        )
    except Exception as err:
        error_code = getattr(err, "response", {}).get("Error", {}).get("Code")
        if error_code != "ResourceAlreadyExistsException":
            return [
                _fail(
                    f"CloudWatch CreateLogStream on {log_group_name} "
                    f"({_format_exception(err)})"
                )
            ]

    results.append(_ok(f"CloudWatch CreateLogStream on {log_group_name}"))

    try:
        logs_client.put_log_events(
            logGroupName=log_group_name,
            logStreamName=stream_name,
            logEvents=[
                {
                    "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                    "message": "aws-check",
                }
            ],
        )
    except Exception as err:
        results.append(
            _fail(
                f"CloudWatch PutLogEvents on {log_group_name} "
                f"({_format_exception(err)})"
            )
        )
        return results

    results.append(_ok(f"CloudWatch PutLogEvents on {log_group_name}"))
    return results


def _run_rig_connectivity_checks(
    runtime: AwsRuntime,
    *,
    rig_name: str,
    log_group_name: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    _run_aws_check(results, "STS caller identity", runtime.sts_client().get_caller_identity)
    _run_aws_check(
        results,
        "IoT DescribeEndpoint (Data-ATS)",
        runtime.iot_data_endpoint,
    )
    _run_aws_check(
        results,
        f"IoT DescribeThingGroup on {rig_name}",
        lambda: runtime.iot_client().describe_thing_group(thingGroupName=rig_name),
    )
    results.extend(_probe_cloudwatch_logs(runtime, log_group_name=log_group_name))
    return results


def _run_device_connectivity_checks(
    runtime: AwsRuntime,
    *,
    thing_name: str,
    video_channel_name: str,
    video_region: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    _run_aws_check(results, "STS caller identity", runtime.sts_client().get_caller_identity)
    endpoint = _run_aws_check(
        results,
        "IoT DescribeEndpoint (Data-ATS)",
        runtime.iot_data_endpoint,
    )
    if isinstance(endpoint, str) and endpoint:
        _run_aws_check(
            results,
            f"IoT Data GetThingShadow on {thing_name}",
            lambda: runtime.client(
                "iot-data",
                endpoint_url=f"https://{endpoint}",
            ).get_thing_shadow(thingName=thing_name),
        )
    _run_aws_check(
        results,
        f"KinesisVideo DescribeSignalingChannel on {video_channel_name}",
        lambda: runtime.client(
            "kinesisvideo",
            region_name=video_region,
        ).describe_signaling_channel(ChannelName=video_channel_name),
    )
    return results


def run_service_check(
    scope: str,
    *,
    environment: Mapping[str, str] | None = None,
    thing_name: str | None = None,
    rig_name: str | None = None,
    log_group_name: str | None = None,
    video_channel_name: str | None = None,
    aws_runtime: AwsRuntime | None = None,
) -> list[CheckResult]:
    env = os.environ if environment is None else environment
    results, resolved = validate_service_environment(scope, env)
    if any(not result.ok for result in results):
        return results

    runtime = aws_runtime
    if runtime is None:
        if env is not os.environ:
            raise RuntimeError(
                "aws_runtime is required when using a custom environment mapping"
            )
        runtime = _build_runtime(scope, region_name=resolved["aws_region"])

    if scope == "rig":
        results.extend(
            _run_rig_connectivity_checks(
                runtime,
                rig_name=rig_name or resolved["rig_name"],
                log_group_name=log_group_name or resolved["log_group_name"],
            )
        )
        return results

    resolved_thing_name = thing_name or resolved["thing_name"]
    results.extend(
        _run_device_connectivity_checks(
            runtime,
            thing_name=resolved_thing_name,
            video_channel_name=video_channel_name or resolved["video_channel_name"],
            video_region=resolved["video_region"],
        )
    )
    return results


def _print_results(results: Sequence[CheckResult]) -> int:
    failures = 0
    for result in results:
        prefix = "ok" if result.ok else "fail"
        print(f"{prefix}: {result.message}")
        if not result.ok:
            failures += 1
    return failures


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shared AWS service preflight checks for rig and device Python runtimes",
    )
    parser.add_argument(
        "--scope",
        choices=sorted(_SCOPE_LABELS),
        required=True,
        help="Python runtime scope to validate",
    )
    parser.add_argument("--thing-name", default="", help="Override thing name for AWS probes")
    parser.add_argument("--rig-name", default="", help="Override rig thing-group name for AWS probes")
    parser.add_argument(
        "--log-group-name",
        default="",
        help="Override CloudWatch log group name for rig AWS probes",
    )
    parser.add_argument(
        "--video-channel-name",
        default="",
        help="Override KVS signaling channel name for device AWS probes",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    scope = args.scope
    scope_label = _SCOPE_LABELS[scope]

    print(f"Checking {scope_label} Python service environment...")
    try:
        results = run_service_check(
            scope,
            thing_name=args.thing_name or None,
            rig_name=args.rig_name or None,
            log_group_name=args.log_group_name or None,
            video_channel_name=args.video_channel_name or None,
        )
    except RuntimeError as err:
        print(f"fail: {scope_label} Python service check setup ({err})")
        print(f"{scope_label} Python service check failed with 1 issue(s)")
        return 1

    failures = _print_results(results)
    if failures:
        print(f"{scope_label} Python service check failed with {failures} issue(s)")
        return 1

    print(f"{scope_label} Python service check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
