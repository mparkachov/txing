from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from .runtime import build_runtime_from_env, parse_mcp_session_c2s_topic

LOGGER = logging.getLogger(__name__)


def _is_mcp_event(event: Mapping[str, Any]) -> bool:
    topic = event.get("mqttTopic")
    return isinstance(topic, str) and parse_mcp_session_c2s_topic(topic) is not None


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    event_type = "mcp" if _is_mcp_event(event) else "schedule"
    thing_name_env = os.getenv("THING_NAME", "").strip()
    try:
        runtime = build_runtime_from_env()
        if event_type == "mcp":
            result = runtime.handle_mcp_message(event)
        else:
            result = runtime.handle_scheduled_wake(event)
    except Exception:
        LOGGER.exception(
            "time lambda invocation failed eventType=%s thingNameEnv=%s",
            event_type,
            thing_name_env,
        )
        raise
    LOGGER.info(
        "time lambda invocation succeeded eventType=%s thingName=%s mode=%s active=%s",
        event_type,
        result.get("thingName"),
        result.get("mode"),
        result.get("active"),
    )
    return result
