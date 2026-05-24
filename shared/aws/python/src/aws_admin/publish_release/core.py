from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import boto3
from botocore.exceptions import ClientError


DEFAULT_GITHUB_REPOSITORY = "mparkachov/txing"
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_LAMBDA_TAG_PREFIX = "lambda-v"
_LEGACY_TAG_PREFIX = "v"
_USER_AGENT = "txing-release-publisher"


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class LambdaAsset:
    artifact_id: str
    asset_name: str


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    assets: dict[str, str]


@dataclass(frozen=True)
class PublishConfig:
    github_repository: str
    lambda_artifact_bucket: str | None
    aws_region: str
    lambda_function_names: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "PublishConfig":
        session = boto3.session.Session()
        region = (
            os.environ.get("TXING_AWS_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or session.region_name
            or ""
        )
        if not region:
            raise PublishError(
                "AWS region is not configured; set AWS CLI region or TXING_AWS_REGION"
            )
        repository = (
            os.environ.get("TXING_GITHUB_REPOSITORY")
            or _repository_from_owner_repo_env()
            or DEFAULT_GITHUB_REPOSITORY
        )
        return cls(
            github_repository=repository,
            lambda_artifact_bucket=os.environ.get("TXING_LAMBDA_ARTIFACT_BUCKET"),
            aws_region=region,
            lambda_function_names=_lambda_function_names_from_env(),
        )

    def deployed_lambda_function_name(self, asset: LambdaAsset) -> str:
        if (
            self.lambda_function_names
            and asset.artifact_id in self.lambda_function_names
        ):
            return self.lambda_function_names[asset.artifact_id]
        raise PublishError(
            f"missing deployed Lambda function name for artifact {asset.artifact_id}"
        )


LAMBDA_ASSETS: tuple[LambdaAsset, ...] = (
    LambdaAsset(
        "txing-witness-lambda",
        "txing-witness-lambda-linux-aarch64.zip",
    ),
    LambdaAsset(
        "txing-cloud-rig-lambda",
        "txing-cloud-rig-lambda-linux-aarch64.zip",
    ),
    LambdaAsset(
        "txing-cloud-mcu-lambda",
        "txing-cloud-mcu-lambda-linux-aarch64.zip",
    ),
)


def _repository_from_owner_repo_env() -> str | None:
    owner = os.environ.get("TXING_GITHUB_OWNER")
    repo = os.environ.get("TXING_GITHUB_REPO")
    if owner and repo:
        return f"{owner}/{repo}"
    return None


def _lambda_function_names_from_env() -> dict[str, str] | None:
    raw = os.environ.get("TXING_LAMBDA_FUNCTIONS_JSON")
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as err:
        raise PublishError("TXING_LAMBDA_FUNCTIONS_JSON must be a JSON object") from err
    if not isinstance(decoded, dict):
        raise PublishError("TXING_LAMBDA_FUNCTIONS_JSON must be a JSON object")
    function_names: dict[str, str] = {}
    for key, value in decoded.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise PublishError(
                "TXING_LAMBDA_FUNCTIONS_JSON must map artifact ids to function names"
            )
        function_names[key] = value
    return function_names


def _version_from_component_tag(tag: str, prefix: str) -> str | None:
    if not tag.startswith(prefix):
        return None
    version = tag[len(prefix) :]
    return version if _SEMVER_RE.fullmatch(version) else None


def _semver_key(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))


def normalize_release_tag(release_ref: str, latest_tag: str | None = None) -> str:
    if not release_ref:
        raise PublishError("release is required")
    if "=" in release_ref:
        raise PublishError("release must be passed positionally, not as name=value")
    if release_ref == "latest":
        if latest_tag is None:
            return "latest"
        tag = latest_tag
    elif release_ref.startswith(_LAMBDA_TAG_PREFIX):
        tag = release_ref
    elif release_ref.startswith(_LEGACY_TAG_PREFIX):
        tag = release_ref
    else:
        tag = f"{_LAMBDA_TAG_PREFIX}{release_ref}"
    if tag.startswith(_LAMBDA_TAG_PREFIX):
        version = tag.removeprefix(_LAMBDA_TAG_PREFIX)
    else:
        version = tag.removeprefix(_LEGACY_TAG_PREFIX)
    if not _SEMVER_RE.fullmatch(version):
        raise PublishError(
            f"release tag must be latest, lambda-vX.Y.Z, vX.Y.Z, or X.Y.Z, got: {tag}"
        )
    return tag


def lambda_version_key(function_name: str, version: str) -> str:
    return f"lambda/{function_name}/{version}/bootstrap.zip"


def lambda_current_key(function_name: str) -> str:
    return f"lambda/{function_name}/current/bootstrap.zip"


def validate_lambda_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            files = [info.filename for info in archive.infolist() if not info.is_dir()]
    except zipfile.BadZipFile as err:
        raise PublishError(f"{path.name} is not a valid zip file") from err
    if files != ["bootstrap"]:
        raise PublishError(
            f"{path.name} must contain exactly one root-level bootstrap executable"
        )


class GitHubReleaseClient:
    def __init__(self, repository: str):
        self.repository = repository
        self._release_cache: dict[str, ReleaseInfo] = {}

    def resolve_release(self, release_ref: str) -> ReleaseInfo:
        if release_ref in self._release_cache:
            return self._release_cache[release_ref]
        tag_for_request = normalize_release_tag(release_ref)
        if tag_for_request == "latest":
            tag, release = self._latest_release_with_prefix(_LAMBDA_TAG_PREFIX)
        else:
            tag = tag_for_request
            quoted_tag = urllib.parse.quote(tag, safe="")
            release = self._get_json(
                f"https://api.github.com/repos/{self.repository}/releases/tags/{quoted_tag}"
            )
            if not isinstance(release, dict):
                raise PublishError(f"GitHub release response for {tag} was not an object")
        assets = {
            asset["name"]: asset["browser_download_url"]
            for asset in release.get("assets", [])
            if asset.get("name") and asset.get("browser_download_url")
        }
        version = _version_from_component_tag(tag, _LAMBDA_TAG_PREFIX)
        if version is None:
            version = tag.removeprefix(_LEGACY_TAG_PREFIX)
        info = ReleaseInfo(tag=tag, version=version, assets=assets)
        self._release_cache[release_ref] = info
        self._release_cache[tag] = info
        return info

    def _latest_release_with_prefix(self, prefix: str) -> tuple[str, dict[str, object]]:
        releases = self._get_json(
            f"https://api.github.com/repos/{self.repository}/releases?per_page=100"
        )
        if not isinstance(releases, list):
            raise PublishError("GitHub releases response was not a list")
        candidates: list[tuple[tuple[int, int, int], str, dict[str, object]]] = []
        for release in releases:
            if not isinstance(release, dict):
                continue
            tag_name = release.get("tag_name")
            if not isinstance(tag_name, str):
                continue
            version = _version_from_component_tag(tag_name, prefix)
            if version is None:
                continue
            candidates.append((_semver_key(version), tag_name, release))
        if not candidates:
            raise PublishError(f"no GitHub releases found for tag prefix {prefix}")
        _, tag, release = max(candidates, key=lambda item: item[0])
        return tag, release

    def download_asset(
        self, release: ReleaseInfo, asset_name: str, destination: Path
    ) -> None:
        url = release.assets.get(asset_name)
        if not url:
            raise PublishError(f"release {release.tag} is missing asset {asset_name}")
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
        except urllib.error.URLError as err:
            raise PublishError(f"failed to download {asset_name}: {err}") from err
        if destination.stat().st_size == 0:
            raise PublishError(f"release asset is empty: {asset_name}")

    def _get_json(self, url: str) -> object:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as err:
            raise PublishError(f"failed to query GitHub release API: {err}") from err


def publish_lambdas(
    release_ref: str,
    config: PublishConfig | None = None,
    github: GitHubReleaseClient | None = None,
    function_filter: set[str] | None = None,
) -> dict[str, object]:
    config = config or PublishConfig.from_env()
    if not config.lambda_artifact_bucket:
        raise PublishError("TXING_LAMBDA_ARTIFACT_BUCKET is required")
    github = github or GitHubReleaseClient(config.github_repository)
    release = github.resolve_release(release_ref)
    s3 = boto3.client("s3")
    lambda_client = boto3.client("lambda")
    published: dict[str, dict[str, str | bool]] = {}
    with tempfile.TemporaryDirectory(prefix="txing-lambda-release.") as work_dir_raw:
        work_dir = Path(work_dir_raw)
        for asset in LAMBDA_ASSETS:
            if function_filter is not None and asset.artifact_id not in function_filter:
                continue
            asset_path = work_dir / asset.asset_name
            github.download_asset(release, asset.asset_name, asset_path)
            validate_lambda_zip(asset_path)
            version_key = lambda_version_key(asset.artifact_id, release.version)
            current_key = lambda_current_key(asset.artifact_id)
            _upload_file_if_missing(
                s3, config.lambda_artifact_bucket, version_key, asset_path
            )
            s3.upload_file(str(asset_path), config.lambda_artifact_bucket, current_key)
            deployed_function_name = config.deployed_lambda_function_name(asset)
            updated = _update_lambda_function(
                lambda_client,
                deployed_function_name,
                config.lambda_artifact_bucket,
                version_key,
            )
            published[asset.artifact_id] = {
                "functionName": deployed_function_name,
                "versionKey": version_key,
                "currentKey": current_key,
                "updated": updated,
            }
    return {
        "releaseTag": release.tag,
        "version": release.version,
        "lambdas": published,
    }


def publish_all(
    release_ref: str, config: PublishConfig | None = None
) -> dict[str, object]:
    lambda_result = publish_lambdas(release_ref, config=config)
    return {
        "ok": True,
        "releaseTag": lambda_result["releaseTag"],
        "version": lambda_result["version"],
        "lambdas": lambda_result["lambdas"],
    }


def _upload_file_if_missing(s3, bucket: str, key: str, path: Path) -> None:
    if _object_exists(s3, bucket, key):
        print(f"artifact already exists: s3://{bucket}/{key}")
        return
    s3.upload_file(str(path), bucket, key)
    print(f"uploaded artifact: s3://{bucket}/{key}")


def _object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _update_lambda_function(
    lambda_client, function_name: str, bucket: str, key: str
) -> bool:
    try:
        lambda_client.get_function(FunctionName=function_name)
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            print(
                f"lambda function {function_name} does not exist yet; seeded S3 bootstrap"
            )
            return False
        raise
    lambda_client.update_function_code(
        FunctionName=function_name,
        S3Bucket=bucket,
        S3Key=key,
    )
    lambda_client.get_waiter("function_updated").wait(FunctionName=function_name)
    print(f"updated lambda function {function_name} to {key}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aws_admin.publish_release")
    subparsers = parser.add_subparsers(dest="command", required=True)
    lambda_parser = subparsers.add_parser("lambda")
    lambda_parser.add_argument("--release", default="latest")
    lambda_parser.add_argument(
        "--function",
        action="append",
        choices=[asset.artifact_id for asset in LAMBDA_ASSETS],
        help="Publish one Lambda artifact id. May be passed more than once.",
    )
    all_parser = subparsers.add_parser("all")
    all_parser.add_argument("--release", default="latest")
    args = parser.parse_args(argv)
    config = PublishConfig.from_env()
    if args.command == "lambda":
        function_filter = set(args.function) if args.function else None
        result = publish_lambdas(
            args.release, config=config, function_filter=function_filter
        )
        result = {"ok": True, **result}
    else:
        result = publish_all(args.release, config=config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
