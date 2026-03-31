from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
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
from .sparkplug import build_device_topic, decode_payload, decode_redcon_command

DEFAULT_THING_NAME = "txing"
DEFAULT_SPARKPLUG_GROUP_ID = "town"
DEFAULT_SPARKPLUG_EDGE_NODE_ID = "rig"
DEFAULT_MESSAGE_TYPE = "both"
DEFAULT_THING_NAME_ENV = "THING_NAME"
DEFAULT_SPARKPLUG_GROUP_ID_ENV = "SPARKPLUG_GROUP_ID"
DEFAULT_SPARKPLUG_EDGE_NODE_ID_ENV = "SPARKPLUG_EDGE_NODE_ID"
DEFAULT_IOT_ENDPOINT_FILE_ENV = "IOT_ENDPOINT_FILE"
DEFAULT_CERT_FILE_ENV = "CERT_FILE"
DEFAULT_KEY_FILE_ENV = "KEY_FILE"
DEFAULT_CA_FILE_ENV = "CA_FILE"


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


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


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
        help="MQTT client id (default: rig-log-<pid>)",
    )
    parser.add_argument(
        "--message-type",
        choices=("dcmd", "ddata", "both"),
        default=DEFAULT_MESSAGE_TYPE,
        help="Sparkplug message type to subscribe to (default: both)",
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
        print(f"rig-sparkplug-log failed: {err}", file=sys.stderr)
        raise SystemExit(2) from err

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
    subscribe_topics: list[tuple[str, int]] = []
    if args.message_type in ("dcmd", "both"):
        subscribe_topics.append((dcmd_topic, 1))
    if args.message_type in ("ddata", "both"):
        subscribe_topics.append((ddata_topic, 1))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=args.client_id or f"rig-log-{os.getpid()}",
        clean_session=True,
        protocol=mqtt.MQTTv311,
    )
    client.tls_set(
        ca_certs=str(args.ca_file),
        certfile=str(args.cert_file),
        keyfile=str(args.key_file),
    )

    def on_connect(
        client: mqtt.Client,
        _userdata: object,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if reason_code != 0:
            print(
                f"rig-sparkplug-log failed: MQTT connect rejected (reason_code={reason_code})",
                file=sys.stderr,
            )
            client.disconnect()
            return
        subscribe_rc, _mid = client.subscribe(subscribe_topics)
        if subscribe_rc != mqtt.MQTT_ERR_SUCCESS:
            print(
                "rig-sparkplug-log failed: unable to subscribe to lifecycle topics "
                f"(rc={subscribe_rc})",
                file=sys.stderr,
            )
            client.disconnect()
            return
        for topic, _qos in subscribe_topics:
            print(f"subscribed to {topic}", flush=True)

    def on_message(
        _client: mqtt.Client,
        _userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        payload_bytes = bytes(msg.payload)
        if msg.topic == dcmd_topic:
            command = decode_redcon_command(payload_bytes)
            if command is None:
                _emit_event(
                    {
                        "topic": msg.topic,
                        "messageType": "DCMD",
                        "payloadHex": payload_bytes.hex(),
                        "error": "invalid Sparkplug DCMD.redcon payload",
                    }
                )
                return
            _emit_event(
                {
                    "topic": msg.topic,
                    "messageType": "DCMD",
                    "redcon": command.value,
                    "seq": command.seq,
                    "timestamp": _format_timestamp_ms(command.timestamp),
                    "timestampMs": command.timestamp,
                }
            )
            return

        if msg.topic == ddata_topic:
            try:
                payload = decode_payload(payload_bytes)
            except Exception as err:
                _emit_event(
                    {
                        "topic": msg.topic,
                        "messageType": "DDATA",
                        "payloadHex": payload_bytes.hex(),
                        "error": str(err),
                    }
                )
                return

            metrics: list[dict[str, object]] = []
            for metric in payload.metrics:
                effective_timestamp = (
                    metric.timestamp
                    if metric.timestamp is not None
                    else payload.timestamp
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
                    "topic": msg.topic,
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
                "topic": msg.topic,
                "payloadHex": payload_bytes.hex(),
                "error": "unexpected topic",
            }
        )

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        connect_rc = client.connect(host=endpoint, port=8883, keepalive=60)
        if connect_rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"failed to initiate AWS IoT MQTT connection (rc={connect_rc})"
            )
        client.loop_forever()
    except KeyboardInterrupt:
        return
    except Exception as err:
        print(f"rig-sparkplug-log failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
