from __future__ import annotations

from typing import Any, Mapping

from .runtime import build_runtime_from_env, parse_mcp_session_c2s_topic


def _is_mcp_event(event: Mapping[str, Any]) -> bool:
    topic = event.get("mqttTopic")
    return isinstance(topic, str) and parse_mcp_session_c2s_topic(topic) is not None


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    runtime = build_runtime_from_env()
    if _is_mcp_event(event):
        return runtime.handle_mcp_message(event)
    return runtime.handle_scheduled_wake(event)
