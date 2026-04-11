from __future__ import annotations

import argparse
import asyncio
import os
import sys

from aws.auth import build_aws_runtime, resolve_aws_region
from aws.mqtt import AwsIotWebsocketConnection, AwsMqttConnectionConfig
from .sparkplug import build_device_topic, build_redcon_payload

DEFAULT_THING_NAME = "txing"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_SPARKPLUG_EDGE_NODE_ID = "rig"
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_SPARKPLUG_GROUP_ID_ENV = "SPARKPLUG_GROUP_ID"
DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV = "SPARKPLUG_EDGE_NODE_ID"
DEFAULT_CONNECT_TIMEOUT = 10.0


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-sparkplug-cmd",
        description="Publish a phase-1 Sparkplug DCMD.redcon command",
    )
    parser.add_argument(
        "--redcon",
        type=int,
        choices=(1, 2, 3, 4),
        required=True,
        help="Target REDCON value to publish",
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
        help="MQTT client id (default: rig-cmd-<pid>)",
    )
    parser.add_argument(
        "--publish-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for MQTT publish acknowledgement (default: 10)",
    )
    return parser.parse_args()


async def _run_publish(args: argparse.Namespace) -> str:
    aws_region = resolve_aws_region()
    if not aws_region:
        raise RuntimeError("could not resolve AWS region for AWS IoT access")

    topic = build_device_topic(
        args.sparkplug_group_id,
        "DCMD",
        args.sparkplug_edge_node_id,
        args.thing_name,
    )
    payload = build_redcon_payload(redcon=args.redcon, seq=0)
    runtime = build_aws_runtime(region_name=aws_region)
    endpoint = runtime.iot_data_endpoint()
    connection = AwsIotWebsocketConnection(
        AwsMqttConnectionConfig(
            endpoint=endpoint,
            client_id=args.client_id or f"rig-cmd-{os.getpid()}",
            region_name=aws_region,
            connect_timeout_seconds=DEFAULT_CONNECT_TIMEOUT,
            operation_timeout_seconds=args.publish_timeout,
        ),
        aws_runtime=runtime,
    )

    try:
        await connection.connect(timeout_seconds=DEFAULT_CONNECT_TIMEOUT)
        await connection.publish(
            topic,
            payload,
            timeout_seconds=args.publish_timeout,
        )
    finally:
        await connection.disconnect(timeout_seconds=DEFAULT_CONNECT_TIMEOUT)

    return topic


def main() -> None:
    args = _parse_args()
    try:
        topic = asyncio.run(_run_publish(args))
    except Exception as err:
        print(f"rig-sparkplug-cmd failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err

    print(f"Published DCMD.redcon={args.redcon} to {topic}")


if __name__ == "__main__":
    main()
