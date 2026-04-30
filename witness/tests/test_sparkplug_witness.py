from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from witness.sparkplug_witness import (
    decode_sparkplug_payload,
    lambda_handler,
    project_sparkplug_message,
)


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint must be non-negative")
    parts = bytearray()
    current = value
    while True:
        next_value = current & 0x7F
        current >>= 7
        if current:
            parts.append(next_value | 0x80)
        else:
            parts.append(next_value)
            return bytes(parts)


def _encode_key(field_number: int, wire_type: int) -> bytes:
    return _encode_varint((field_number << 3) | wire_type)


def _encode_length_delimited(field_number: int, payload: bytes) -> bytes:
    return _encode_key(field_number, 2) + _encode_varint(len(payload)) + payload


def _encode_metric(
    *,
    name: str,
    int_value: int | None = None,
    long_value: int | None = None,
    bool_value: bool | None = None,
    string_value: str | None = None,
) -> bytes:
    payload = bytearray()
    payload.extend(_encode_length_delimited(1, name.encode("utf-8")))
    if int_value is not None:
        payload.extend(_encode_key(10, 0))
        payload.extend(_encode_varint(int_value))
    if long_value is not None:
        payload.extend(_encode_key(11, 0))
        payload.extend(_encode_varint(long_value))
    if bool_value is not None:
        payload.extend(_encode_key(12, 0))
        payload.extend(_encode_varint(1 if bool_value else 0))
    if string_value is not None:
        payload.extend(_encode_length_delimited(13, string_value.encode("utf-8")))
    return bytes(payload)


def _encode_payload(
    *,
    timestamp: int | None = 1710000000000,
    seq: int | None = 7,
    metrics: list[bytes],
) -> str:
    payload = bytearray()
    if timestamp is not None:
        payload.extend(_encode_key(1, 0))
        payload.extend(_encode_varint(timestamp))
    for metric in metrics:
        payload.extend(_encode_length_delimited(2, metric))
    if seq is not None:
        payload.extend(_encode_key(3, 0))
        payload.extend(_encode_varint(seq))
    return base64.b64encode(bytes(payload)).decode("ascii")


class SparkplugWitnessTests(unittest.TestCase):
    def test_decode_device_birth_projects_nested_metrics(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="redcon", int_value=1),
                _encode_metric(name="batteryMv", int_value=3795),
                _encode_metric(name="services/demo/available", bool_value=True),
            ]
        )

        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/DBIRTH/rig/unit-1",
        )

        assert message is not None
        self.assertEqual(message.device_id, "unit-1")
        self.assertEqual(message.message_type, "DBIRTH")
        self.assertEqual(
            message.metrics,
            {
                "redcon": 1,
                "batteryMv": 3795,
                "services": {
                    "demo": {
                        "available": True,
                    }
                },
            },
        )

    def test_decode_node_birth_omits_device_id_and_normalizes_metric_paths(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="redcon", int_value=2),
                _encode_metric(name="bdSeq", long_value=42),
            ]
        )

        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/NBIRTH/rig",
        )

        assert message is not None
        self.assertIsNone(message.device_id)
        self.assertEqual(
            message.metrics,
            {
                "redcon": 2,
                "bdSeq": 42,
            },
        )

    def test_project_node_birth_replaces_metrics_with_topic_payload_projection(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="redcon", int_value=1),
                _encode_metric(name="bdSeq", long_value=42),
            ]
        )
        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/NBIRTH/rig",
        )

        assert message is not None
        with patch("witness.sparkplug_witness._resolve_thing_name", return_value="rig-main"), patch(
            "witness.sparkplug_witness._replace_metrics"
        ) as replace_metrics:
            projected_thing_name = project_sparkplug_message(message, 1710000000999)

        self.assertEqual(projected_thing_name, "rig-main")
        replace_metrics.assert_called_once()
        thing_name, reported_payload = replace_metrics.call_args.args
        self.assertEqual(thing_name, "rig-main")
        self.assertEqual(
            reported_payload,
            {
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "NBIRTH",
                    "edgeNodeId": "rig",
                },
                "payload": {
                    "timestamp": 1710000000000,
                    "seq": 7,
                    "metrics": {
                        "redcon": 1,
                        "bdSeq": 42,
                    },
                },
                "projection": {
                    "observedAt": 1710000000999,
                },
            },
        )

    def test_decode_ignores_unsupported_metric_types_without_failing(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="redcon", int_value=3),
                _encode_metric(name="unsupported-only-name"),
            ]
        )

        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/DDATA/rig/unit-1",
        )

        assert message is not None
        self.assertEqual(message.metrics, {"redcon": 3})

    def test_project_device_birth_replaces_metrics(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="redcon", int_value=1),
                _encode_metric(name="batteryMv", int_value=3795),
            ]
        )
        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/DBIRTH/rig/unit-1",
        )

        assert message is not None
        with patch("witness.sparkplug_witness._resolve_thing_name", return_value="unit-1"), patch(
            "witness.sparkplug_witness._replace_metrics"
        ) as replace_metrics:
            projected_thing_name = project_sparkplug_message(message, 1710000000999)

        self.assertEqual(projected_thing_name, "unit-1")
        replace_metrics.assert_called_once()
        thing_name, reported_payload = replace_metrics.call_args.args
        self.assertEqual(thing_name, "unit-1")
        self.assertEqual(
            reported_payload,
            {
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "DBIRTH",
                    "edgeNodeId": "rig",
                    "deviceId": "unit-1",
                },
                "payload": {
                    "timestamp": 1710000000000,
                    "seq": 7,
                    "metrics": {
                        "redcon": 1,
                        "batteryMv": 3795,
                    },
                },
                "projection": {
                    "observedAt": 1710000000999,
                },
            },
        )

    def test_project_device_data_merges_nested_metrics_without_dropping_others(self) -> None:
        encoded_payload = _encode_payload(
            metrics=[
                _encode_metric(name="services/demo/available", bool_value=True),
            ]
        )
        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/DDATA/rig/unit-1",
        )

        assert message is not None
        with patch("witness.sparkplug_witness._resolve_thing_name", return_value="unit-1"), patch(
            "witness.sparkplug_witness._merge_metrics"
        ) as merge_metrics:
            project_sparkplug_message(message, 1710000001999)

        merge_metrics.assert_called_once()
        _, reported_payload = merge_metrics.call_args.args
        self.assertEqual(
            reported_payload,
            {
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "DDATA",
                    "edgeNodeId": "rig",
                    "deviceId": "unit-1",
                },
                "payload": {
                    "timestamp": 1710000000000,
                    "seq": 7,
                    "metrics": {
                        "services": {
                            "demo": {
                                "available": True,
                            }
                        }
                    },
                },
                "projection": {
                    "observedAt": 1710000001999,
                },
            },
        )

    def test_project_device_death_replaces_metrics_with_death_payload(self) -> None:
        encoded_payload = _encode_payload(
            timestamp=None,
            seq=None,
            metrics=[],
        )
        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/DDEATH/rig/unit-1",
        )

        assert message is not None
        with patch("witness.sparkplug_witness._resolve_thing_name", return_value="unit-1"), patch(
            "witness.sparkplug_witness._replace_metrics"
        ) as replace_metrics:
            project_sparkplug_message(message, 1710000002999)

        replace_metrics.assert_called_once()
        _, reported_payload = replace_metrics.call_args.args
        self.assertEqual(
            reported_payload,
            {
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "DDEATH",
                    "edgeNodeId": "rig",
                    "deviceId": "unit-1",
                },
                "payload": {
                    "timestamp": None,
                    "seq": None,
                    "metrics": {},
                },
                "projection": {
                    "observedAt": 1710000002999,
                },
            },
        )

    def test_project_node_death_replaces_metrics_with_death_payload(self) -> None:
        encoded_payload = _encode_payload(
            timestamp=None,
            seq=None,
            metrics=[
                _encode_metric(name="bdSeq", long_value=42),
                _encode_metric(name="redcon", int_value=4),
            ],
        )
        message = decode_sparkplug_payload(
            encoded_payload,
            "spBv1.0/town/NDEATH/rig",
        )

        assert message is not None
        with patch("witness.sparkplug_witness._resolve_thing_name", return_value="rig-main"), patch(
            "witness.sparkplug_witness._replace_metrics"
        ) as replace_metrics:
            project_sparkplug_message(message, 1710000003999)

        replace_metrics.assert_called_once()
        _, reported_payload = replace_metrics.call_args.args
        self.assertEqual(
            reported_payload,
            {
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "NDEATH",
                    "edgeNodeId": "rig",
                },
                "payload": {
                    "timestamp": None,
                    "seq": None,
                    "metrics": {
                        "bdSeq": 42,
                        "redcon": 4,
                    },
                },
                "projection": {
                    "observedAt": 1710000003999,
                },
            },
        )

    def test_rejects_invalid_topic_arity_and_message_pairings(self) -> None:
        encoded_payload = _encode_payload(metrics=[])
        self.assertIsNone(decode_sparkplug_payload(encoded_payload, "spBv1.0/town/DBIRTH/rig"))
        self.assertIsNone(
            decode_sparkplug_payload(encoded_payload, "spBv1.0/town/NBIRTH/rig/unit-1")
        )
        self.assertIsNone(decode_sparkplug_payload(encoded_payload, "spBv1.0/town//rig"))

    def test_lambda_handler_ignores_unsupported_topics(self) -> None:
        result = lambda_handler(
            {
                "mqttTopic": "txings/unit-1/video/status",
                "payloadBase64": "",
                "observedAt": 123,
            },
            None,
        )

        self.assertEqual(result, {"status": "ignored", "reason": "unsupported-topic"})


if __name__ == "__main__":
    unittest.main()
