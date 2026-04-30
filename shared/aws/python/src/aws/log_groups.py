from __future__ import annotations

LOG_GROUP_PREFIX = "txing"
DEFAULT_LOG_RETENTION_DAYS = 30


def build_rig_log_group_name(*, town_thing_name: str, rig_thing_name: str) -> str:
    return f"{LOG_GROUP_PREFIX}/{town_thing_name}/{rig_thing_name}"


def build_device_log_group_name(
    *,
    town_thing_name: str,
    rig_thing_name: str,
    device_thing_name: str,
) -> str:
    return (
        f"{LOG_GROUP_PREFIX}/{town_thing_name}/{rig_thing_name}/{device_thing_name}"
    )
