from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
import sys

from .aws_auth import build_aws_runtime, resolve_aws_region
from .aws_mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from .sparkplug import build_device_topic, decode_payload, decode_redcon_command

DEFAULT_THING_NAME = "txing"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_SPARKPLUG_EDGE_NODE_ID = "rig"
DEFAULT_MESSAGE_TYPE = "both"
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_SPARKPLUG_GROUP_ID_ENV = "SPARKPLUG_GROUP_ID"
DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV = "SPARKPLUG_EDGE_NODE_ID"
DEFAULT_CONNECT_TIMEOUT = 10.0


def _format_timestamp_ms(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _emit_event(event: dict[str, object]) -> None:
    print(json.dumps(event, indent=2), flush=True)


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-sparkplug-log",
        description="Subscribe to phase-1 Sparkplug lifecycle topics and decode payloads",
    )
    parser.add_argument(
        "--thing-name",
        default=_env_text(DEFAULT_THING_NAME_ENV, DEFAULT_THING_NAME),
        help="Sparkplug device id / txing thing name (default: txing)",
    )
    parser.add_argument(
        "--sparkplug-group-id",
        default=_env_text(DEFAULT_SPARKPLUG_GROUP_ID_ENV, DEFAULT_SPARKPLUG_GROUP_ID),
        help="Sparkplug group id (default: town)",
    )
    parser.add_argument(
        "--sparkplug-edge-node-id",
        default=_env_text(
            DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV,
            DEFAULT_SPARKPLUG_EDGE_NODE_ID,
        ),
        help="Sparkplug edge node id (default: rig)",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="MQTT client id (default: rig-log-<pid>)",
    )
    parser.add_argument(
        "--message-type",
        choices=("dcmd", "ddata", "both"),
        default=DEFAULT_MESSAGE_TYPE,
        help="Sparkplug message type to subscribe to (default: both)",
    )
    return parser.parse_args()


def _handle_message(
    *,
    dcmd_topic: str,
    ddata_topic: str,
    topic: str,
    payload_bytes: bytes,
) -> None:
    if topic == dcmd_topic:
        command = decode_redcon_command(payload_bytes)
        if command is None:
            _emit_event(
                {
                    "topic": topic,
                    "messageType": "DCMD",
                    "payloadHex": payload_bytes.hex(),
                    "error": "invalid Sparkplug DCMD.redcon payload",
                }
            )
            return
        _emit_event(
            {
                "topic": topic,
                "messageType": "DCMD",
                "redcon": command.value,
                "seq": command.seq,
                "timestamp": _format_timestamp_ms(command.timestamp),
                "timestampMs": command.timestamp,
            }
        )
        return

    if topic == ddata_topic:
        try:
            payload = decode_payload(payload_bytes)
        except Exception as err:
            _emit_event(
                {
                    "topic": topic,
                    "messageType": "DDATA",
                    "payloadHex": payload_bytes.hex(),
                    "error": str(err),
                }
            )
            return

        metrics: list[dict[str, object]] = []
        for metric in payload.metrics:
            effective_timestamp = (
                metric.timestamp if metric.timestamp is not None else payload.timestamp
            )
            metrics.append(
                {
                    "name": metric.name,
                    "datatype": metric.datatype.name,
                    "value": (
                        metric.int_value
                        if metric.int_value is not None
                        else metric.long_value
                    ),
                    "timestamp": _format_timestamp_ms(effective_timestamp),
                    "timestampMs": effective_timestamp,
                }
            )
        _emit_event(
            {
                "topic": topic,
                "messageType": "DDATA",
                "seq": payload.seq,
                "timestamp": _format_timestamp_ms(payload.timestamp),
                "timestampMs": payload.timestamp,
                "metrics": metrics,
            }
        )
        return

    _emit_event(
        {
            "topic": topic,
            "payloadHex": payload_bytes.hex(),
            "error": "unexpected topic",
        }
    )


async def _run_log(args: argparse.Namespace) -> None:
    aws_region = resolve_aws_region()
    if not aws_region:
        raise RuntimeError("could not resolve AWS region for AWS IoT access")

    dcmd_topic = build_device_topic(
        args.sparkplug_group_id,
        "DCMD",
        args.sparkplug_edge_node_id,
        args.thing_name,
    )
    ddata_topic = build_device_topic(
        args.sparkplug_group_id,
        "DDATA",
        args.sparkplug_edge_node_id,
        args.thing_name,
    )
    subscribe_topics: list[str] = []
    if args.message_type in ("dcmd", "both"):
        subscribe_topics.append(dcmd_topic)
    if args.message_type in ("ddata", "both"):
        subscribe_topics.append(ddata_topic)

    runtime = build_aws_runtime(region_name=aws_region)
    endpoint = runtime.iot_data_endpoint()
    connection = AwsIotWebsocketConnection(
        AwsMqttConnectionConfig(
            endpoint=endpoint,
            client_id=args.client_id or f"rig-log-{os.getpid()}",
            region_name=aws_region,
            connect_timeout_seconds=DEFAULT_CONNECT_TIMEOUT,
            operation_timeout_seconds=DEFAULT_CONNECT_TIMEOUT,
        ),
        aws_runtime=runtime,
    )

    try:
        await connection.connect(timeout_seconds=DEFAULT_CONNECT_TIMEOUT)
        for topic in subscribe_topics:
            await connection.subscribe(
                topic,
                lambda message_topic, payload_bytes, *, _dcmd=dcmd_topic, _ddata=ddata_topic: _handle_message(
                    dcmd_topic=_dcmd,
                    ddata_topic=_ddata,
                    topic=message_topic,
                    payload_bytes=payload_bytes,
                ),
                timeout_seconds=DEFAULT_CONNECT_TIMEOUT,
            )
            print(f"subscribed to {topic}", flush=True)

        while True:
            await asyncio.sleep(3600)
    finally:
        await connection.disconnect(timeout_seconds=DEFAULT_CONNECT_TIMEOUT)


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_run_log(args))
    except KeyboardInterrupt:
        return
    except Exception as err:
        print(f"rig-sparkplug-log failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err


if __name__ == "__main__":
    main()
