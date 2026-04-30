from __future__ import annotations

from typing import Any, Mapping


SPARKPLUG_NAMESPACE = "spBv1.0"


def build_sparkplug_shadow_payload(
    *,
    payload: Mapping[str, Any],
    topic: Mapping[str, Any] | None = None,
    projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reported: dict[str, Any] = {
        "payload": dict(payload),
    }
    if topic is not None:
        reported["topic"] = dict(topic)
    if projection:
        reported["projection"] = dict(projection)
    return {
        "state": {
            "reported": reported,
        }
    }


def build_static_group_shadow_payload(group_id: str) -> dict[str, Any]:
    _ = group_id
    return build_sparkplug_shadow_payload(
        payload={
            "metrics": {
                "redcon": 1,
            }
        }
    )


def build_offline_node_shadow_payload(
    *,
    group_id: str,
    edge_node_id: str,
) -> dict[str, Any]:
    return build_sparkplug_shadow_payload(
        topic={
            "namespace": SPARKPLUG_NAMESPACE,
            "groupId": group_id,
            "messageType": "NDEATH",
            "edgeNodeId": edge_node_id,
        },
        payload={
            "metrics": {
                "redcon": 4,
            },
        },
    )


def build_offline_device_shadow_payload(
    *,
    group_id: str,
    edge_node_id: str,
    device_id: str,
) -> dict[str, Any]:
    return build_sparkplug_shadow_payload(
        topic={
            "namespace": SPARKPLUG_NAMESPACE,
            "groupId": group_id,
            "messageType": "DDEATH",
            "edgeNodeId": edge_node_id,
            "deviceId": device_id,
        },
        payload={
            "metrics": {},
        },
    )
