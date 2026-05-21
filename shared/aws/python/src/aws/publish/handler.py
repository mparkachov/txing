from __future__ import annotations

from .core import PublishConfig, PublishError, publish_all


def lambda_handler(event, context):
    if event is None:
        event = {}
    if not isinstance(event, dict):
        raise PublishError("publisher event must be a JSON object")
    release = event.get("release", "latest")
    if not isinstance(release, str):
        raise PublishError("release must be a string")
    return publish_all(release, config=PublishConfig.from_env())
