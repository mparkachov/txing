from __future__ import annotations

import json
import logging

from botocore.exceptions import BotoCoreError, ClientError

from .core import (
    GitHubReleaseClient,
    PublishConfig,
    PublishError,
    normalize_release_tag,
    publish_all,
)


_LOG = logging.getLogger(__name__)


def lambda_handler(event, context):
    if event is None:
        event = {}
    if not isinstance(event, dict):
        raise PublishError("publisher event must be a JSON object")
    request_context = event.get("requestContext")
    if event.get("version") == "2.0" and isinstance(request_context, dict):
        http = request_context.get("http")
        if isinstance(http, dict):
            return _publish_from_url(event, http)
    release = event.get("release", "latest")
    if not isinstance(release, str):
        raise PublishError("release must be a string")
    return publish_all(release, config=PublishConfig.from_env())


def _publish_from_url(event: dict, http: dict) -> dict:
    if event.get("rawPath") != "/":
        return _http_response(404, {"ok": False, "error": "use POST /"})
    if http.get("method") != "POST":
        response = _http_response(405, {"ok": False, "error": "use POST /"})
        response["headers"]["allow"] = "POST"
        return response

    try:
        if event.get("isBase64Encoded"):
            raise PublishError("expected a JSON request body")
        payload = json.loads(event.get("body"))
        if not isinstance(payload, dict) or payload.keys() != {"release"}:
            raise PublishError("expected a release tag")
        release = payload["release"]
        if not isinstance(release, str) or not release.startswith("lambda-v"):
            raise PublishError("expected a Lambda release tag")
        normalize_release_tag(release)
    except (ValueError, TypeError, PublishError):
        return _http_response(
            400, {"ok": False, "error": "expected a lambda-vX.Y.Z release tag"}
        )

    try:
        config = PublishConfig.from_env()
        github = GitHubReleaseClient(config.github_repository)
        current_release = github.resolve_release("latest")
        if release != current_release.tag:
            return _http_response(
                409,
                {
                    "ok": False,
                    "error": "requested release is not current",
                    "releaseTag": current_release.tag,
                },
            )
        result = publish_all("latest", config=config, github=github, require_all=True)
    except (PublishError, BotoCoreError, ClientError):
        _LOG.exception("Lambda release publication failed for %s", release)
        return _http_response(
            500, {"ok": False, "error": "Lambda release publication failed"}
        )
    return _http_response(200, result)


def _http_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
