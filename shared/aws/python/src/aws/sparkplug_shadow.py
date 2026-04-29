from __future__ import annotations

from typing import Any, Mapping


def _base_session(
    *,
    entity_kind: str,
    group_id: str,
    online: bool,
    edge_node_id: str | None = None,
    device_id: str | None = None,
    message_type: str | None = None,
    seq: int | None = None,
    sparkplug_timestamp: int | None = None,
    observed_at: int | None = None,
) -> dict[str, Any]:
    session: dict[str, Any] = {
        "entityKind": entity_kind,
        "groupId": group_id,
        "online": online,
    }
    if edge_node_id is not None:
        session["edgeNodeId"] = edge_node_id
    if device_id is not None:
        session["deviceId"] = device_id
    if message_type is not None:
        session["messageType"] = message_type
    if seq is not None:
        session["seq"] = seq
    if sparkplug_timestamp is not None:
        session["sparkplugTimestamp"] = sparkplug_timestamp
    if observed_at is not None:
        session["observedAt"] = observed_at
    return session


def build_sparkplug_shadow_payload(
    *,
    session: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "state": {
            "reported": {
                "session": dict(session),
                "metrics": dict(metrics),
            }
        }
    }


def build_static_group_shadow_payload(group_id: str) -> dict[str, Any]:
    return build_sparkplug_shadow_payload(
        session=_base_session(
            entity_kind="group",
            group_id=group_id,
            online=True,
        ),
        metrics={"redcon": 1},
    )


def build_offline_node_shadow_payload(
    *,
    group_id: str,
    edge_node_id: str,
) -> dict[str, Any]:
    return build_sparkplug_shadow_payload(
        session=_base_session(
            entity_kind="node",
            group_id=group_id,
            edge_node_id=edge_node_id,
            message_type="NDEATH",
            online=False,
        ),
        metrics={},
    )


def build_offline_device_shadow_payload(
    *,
    group_id: str,
    edge_node_id: str,
    device_id: str,
) -> dict[str, Any]:
    return build_sparkplug_shadow_payload(
        session=_base_session(
            entity_kind="device",
            group_id=group_id,
            edge_node_id=edge_node_id,
            device_id=device_id,
            message_type="DDEATH",
            online=False,
        ),
        metrics={},
    )
