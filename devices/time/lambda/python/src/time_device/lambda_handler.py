from __future__ import annotations

import logging
from typing import Any, Mapping

from .runtime import (
    build_runtime_from_env,
    handle_scheduled_wake_for_time_devices_from_env,
    parse_mcp_session_c2s_topic,
)

LOGGER = logging.getLogger(__name__)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    topic = event.get("mqttTopic")
    parsed_topic = parse_mcp_session_c2s_topic(topic) if isinstance(topic, str) else None
    event_type = "mcp" if parsed_topic is not None else "schedule"
    try:
        if parsed_topic is not None:
            thing_name, _session_id = parsed_topic
            runtime = build_runtime_from_env(thing_name=thing_name)
            result = runtime.handle_mcp_message(event)
        else:
            result = handle_scheduled_wake_for_time_devices_from_env(event)
    except Exception:
        LOGGER.exception("time lambda invocation failed eventType=%s", event_type)
        raise
    LOGGER.info(
        "time lambda invocation succeeded eventType=%s thingName=%s thingCount=%s mode=%s active=%s",
        event_type,
        result.get("thingName"),
        result.get("thingCount"),
        result.get("mode"),
        result.get("active"),
    )
    return result
