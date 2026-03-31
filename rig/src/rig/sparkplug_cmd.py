from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

from .repo_paths import (
    DEFAULT_CA_FILE,
    DEFAULT_CERT_FILE,
    DEFAULT_IOT_ENDPOINT_FILE,
    DEFAULT_KEY_FILE,
)
from .sparkplug import build_device_topic, build_redcon_payload

DEFAULT_THING_NAME = "txing"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_SPARKPLUG_EDGE_NODE_ID = "rig"
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_SPARKPLUG_GROUP_ID_ENV = "SPARKPLUG_GROUP_ID"
DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV = "SPARKPLUG_EDGE_NODE_ID"
DEFAULT_IOT_ENDPOINT_FILE_ENV = "IOT_ENDPOINT_FILE"
DEFAULT_CERT_FILE_ENV = "CERT_FILE"
DEFAULT_KEY_FILE_ENV = "KEY_FILE"
DEFAULT_CA_FILE_ENV = "CA_FILE"


def _env_text(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def _read_iot_endpoint(explicit_endpoint: str | None, endpoint_file: Path) -> str:
    if explicit_endpoint:
        endpoint = explicit_endpoint.strip()
        if endpoint:
            return endpoint

    try:
        endpoint = endpoint_file.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise RuntimeError(
            f"failed to read AWS IoT endpoint file {endpoint_file}: {err}"
        ) from err
    if not endpoint:
        raise RuntimeError(f"AWS IoT endpoint file {endpoint_file} is empty")
    return endpoint


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{description} not found: {path}")


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
        "--iot-endpoint",
        default=None,
        help="AWS IoT data endpoint hostname; if omitted, --iot-endpoint-file is used",
    )
    parser.add_argument(
        "--iot-endpoint-file",
        type=Path,
        default=_env_path(DEFAULT_IOT_ENDPOINT_FILE_ENV, DEFAULT_IOT_ENDPOINT_FILE),
        help=f"File containing AWS IoT endpoint (default: {DEFAULT_IOT_ENDPOINT_FILE})",
    )
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=_env_path(DEFAULT_CERT_FILE_ENV, DEFAULT_CERT_FILE),
        help=f"Client certificate PEM file (default: {DEFAULT_CERT_FILE})",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=_env_path(DEFAULT_KEY_FILE_ENV, DEFAULT_KEY_FILE),
        help=f"Client private key file (default: {DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        default=_env_path(DEFAULT_CA_FILE_ENV, DEFAULT_CA_FILE),
        help=f"Root CA file (default: {DEFAULT_CA_FILE})",
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


def main() -> None:
    args = _parse_args()
    try:
        endpoint = _read_iot_endpoint(args.iot_endpoint, args.iot_endpoint_file)
        _require_file(args.cert_file, "AWS IoT client certificate")
        _require_file(args.key_file, "AWS IoT client private key")
        _require_file(args.ca_file, "AWS IoT root CA")
    except RuntimeError as err:
        print(f"rig-sparkplug-cmd failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

    topic = build_device_topic(
        args.sparkplug_group_id,
        "DCMD",
        args.sparkplug_edge_node_id,
        args.thing_name,
    )
    payload = build_redcon_payload(redcon=args.redcon, seq=0)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=args.client_id or f"rig-cmd-{os.getpid()}",
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )
    client.tls_set(
        ca_certs=str(args.ca_file),
        certfile=str(args.cert_file),
        keyfile=str(args.key_file),
    )

    try:
        connect_rc = client.connect(host=endpoint, port=8883, keepalive=60)
        if connect_rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"failed to initiate AWS IoT MQTT connection (rc={connect_rc})"
            )
        client.loop_start()
        info = client.publish(topic, payload=payload, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"failed to publish Sparkplug command (rc={info.rc})")
        wait_result = info.wait_for_publish(timeout=args.publish_timeout)
        if wait_result is False:
            raise TimeoutError(
                f"timed out waiting {args.publish_timeout:.1f}s for Sparkplug publish acknowledgement"
            )
    except Exception as err:
        print(f"rig-sparkplug-cmd failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
    finally:
        try:
            client.disconnect()
        finally:
            client.loop_stop()

    print(f"Published DCMD.redcon={args.redcon} to {topic}")


if __name__ == "__main__":
    main()
