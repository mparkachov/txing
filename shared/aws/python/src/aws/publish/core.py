from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import boto3
from botocore.exceptions import ClientError


DEFAULT_GITHUB_REPOSITORY = "mparkachov/txing"
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_USER_AGENT = "txing-release-publisher"


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class LambdaAsset:
    function_name: str
    asset_name: str


@dataclass(frozen=True)
class RigComponent:
    component_name: str
    asset_name: str
    binary_name: str


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    assets: dict[str, str]


@dataclass(frozen=True)
class PublishConfig:
    github_repository: str
    lambda_artifact_bucket: str | None
    greengrass_artifact_bucket: str | None
    aws_region: str
    txing_version_base: str | None = None

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
            greengrass_artifact_bucket=os.environ.get(
                "TXING_GREENGRASS_ARTIFACT_BUCKET"
            ),
            aws_region=region,
            txing_version_base=os.environ.get("TXING_VERSION_BASE"),
        )


LAMBDA_ASSETS: tuple[LambdaAsset, ...] = (
    LambdaAsset("txing-witness-lambda", "txing-witness-lambda-linux-aarch64.zip"),
    LambdaAsset("txing-enlist-lambda", "txing-enlist-lambda-linux-aarch64.zip"),
    LambdaAsset("txing-cloud-rig-lambda", "txing-cloud-rig-lambda-linux-aarch64.zip"),
    LambdaAsset("txing-cloud-mcu-lambda", "txing-cloud-mcu-lambda-linux-aarch64.zip"),
)

RIG_COMPONENTS: tuple[RigComponent, ...] = (
    RigComponent(
        "dev.txing.rig.SparkplugManager",
        "txing-sparkplug-manager-linux-aarch64.tar.gz",
        "txing-sparkplug-manager",
    ),
    RigComponent(
        "dev.txing.rig.BleConnectivity",
        "txing-ble-connectivity-linux-aarch64.tar.gz",
        "txing-ble-connectivity",
    ),
    RigComponent(
        "dev.txing.rig.AwsConnectivity",
        "txing-aws-connectivity-linux-aarch64.tar.gz",
        "txing-aws-connectivity",
    ),
)


def _repository_from_owner_repo_env() -> str | None:
    owner = os.environ.get("TXING_GITHUB_OWNER")
    repo = os.environ.get("TXING_GITHUB_REPO")
    if owner and repo:
        return f"{owner}/{repo}"
    return None


def normalize_release_tag(release_ref: str, latest_tag: str | None = None) -> str:
    if not release_ref:
        raise PublishError("release is required")
    if "=" in release_ref:
        raise PublishError("release must be passed positionally, not as name=value")
    if release_ref == "latest":
        if latest_tag is None:
            return "latest"
        tag = latest_tag
    elif release_ref.startswith("v"):
        tag = release_ref
    else:
        tag = f"v{release_ref}"
    version = tag.removeprefix("v")
    if not _SEMVER_RE.fullmatch(version):
        raise PublishError(f"release tag must be SemVer vX.Y.Z, got: {tag}")
    return tag


def lambda_version_key(function_name: str, version: str) -> str:
    return f"lambda/{function_name}/{version}/bootstrap.zip"


def lambda_current_key(function_name: str) -> str:
    return f"lambda/{function_name}/current/bootstrap.zip"


def rig_artifact_key(component_name: str, version: str, binary_name: str) -> str:
    return f"artifacts/{component_name}/{version}/{binary_name}"


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


def validate_and_extract_rig_binary(
    archive_path: Path, binary_name: str, output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            files = [member for member in archive.getmembers() if member.isfile()]
            normalized_names = [
                member.name[2:] if member.name.startswith("./") else member.name
                for member in files
            ]
            if normalized_names != [binary_name]:
                raise PublishError(
                    f"{archive_path.name} must contain exactly root-level {binary_name}"
                )
            member = files[0]
            if "/" in normalized_names[0]:
                raise PublishError(
                    f"{archive_path.name} must contain root-level {binary_name}"
                )
            if member.mode & stat.S_IXUSR == 0:
                raise PublishError(
                    f"{binary_name} in {archive_path.name} is not executable"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise PublishError(
                    f"could not extract {binary_name} from {archive_path.name}"
                )
            output_path = output_dir / binary_name
            with extracted, output_path.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            os.chmod(output_path, member.mode & 0o777)
            return output_path
    except tarfile.TarError as err:
        raise PublishError(f"{archive_path.name} is not a valid tar.gz file") from err


def greengrass_components_for_target(
    version: str, rig_type: str
) -> dict[str, dict[str, str]]:
    if rig_type == "raspi":
        component_names = (
            "dev.txing.rig.SparkplugManager",
            "dev.txing.rig.BleConnectivity",
        )
    elif rig_type == "cloud":
        component_names = (
            "dev.txing.rig.SparkplugManager",
            "dev.txing.rig.AwsConnectivity",
        )
    else:
        raise PublishError(f"unsupported Greengrass rig type: {rig_type}")
    return {name: {"componentVersion": version} for name in component_names}


def greengrass_recipe(
    component_name: str,
    version: str,
    artifact_uri: str,
    aws_region: str,
    iot_data_endpoint: str,
    txing_version_base: str | None = None,
) -> dict[str, object]:
    txing_version_base = txing_version_base or version
    if component_name == "dev.txing.rig.SparkplugManager":
        return _sparkplug_manager_recipe(
            version, artifact_uri, aws_region, iot_data_endpoint, txing_version_base
        )
    if component_name == "dev.txing.rig.BleConnectivity":
        return _ble_connectivity_recipe(version, artifact_uri)
    if component_name == "dev.txing.rig.AwsConnectivity":
        return _aws_connectivity_recipe(
            version, artifact_uri, aws_region, iot_data_endpoint, txing_version_base
        )
    raise PublishError(f"unsupported Greengrass component: {component_name}")


def _base_recipe(
    component_name: str,
    version: str,
    description: str,
    artifact_uri: str,
    run_script: str,
    default_configuration: dict[str, object],
    dependencies: dict[str, object] | None = None,
) -> dict[str, object]:
    recipe: dict[str, object] = {
        "RecipeFormatVersion": "2020-01-25",
        "ComponentName": component_name,
        "ComponentVersion": version,
        "ComponentType": "aws.greengrass.generic",
        "ComponentDescription": description,
        "ComponentPublisher": "txing",
        "ComponentConfiguration": {"DefaultConfiguration": default_configuration},
        "Manifests": [
            {
                "Platform": {"os": "linux", "runtime": "aws_nucleus_lite"},
                "Lifecycle": {"run": {"Script": run_script}},
                "Artifacts": [
                    {
                        "Uri": artifact_uri,
                        "Unarchive": "NONE",
                        "Permission": {"Read": "ALL", "Execute": "ALL"},
                    }
                ],
            }
        ],
    }
    if dependencies:
        recipe["ComponentDependencies"] = dependencies
    return recipe


def _sparkplug_manager_recipe(
    version: str,
    artifact_uri: str,
    aws_region: str,
    iot_data_endpoint: str,
    txing_version_base: str,
) -> dict[str, object]:
    return _base_recipe(
        "dev.txing.rig.SparkplugManager",
        version,
        "txing rig Sparkplug lifecycle manager.",
        artifact_uri,
        "\n".join(
            [
                f'export AWS_REGION="{aws_region}"',
                f'export AWS_DEFAULT_REGION="{aws_region}"',
                f'export AWS_IOT_ENDPOINT="{iot_data_endpoint}"',
                f'export TXING_VERSION_BASE="{txing_version_base}"',
                f'export TXING_VERSION="{version}"',
                'exec "{artifacts:path}/txing-sparkplug-manager" \\',
                f'  --iot-endpoint "{iot_data_endpoint}" \\',
                f'  --aws-region "{aws_region}" \\',
                '  --inventory-interval-seconds "{configuration:/InventoryIntervalSeconds}" \\',
                '  --command-deadline-ms "{configuration:/CommandDeadlineMs}"',
            ]
        ),
        {
            "InventoryIntervalSeconds": 30,
            "CommandDeadlineMs": 60000,
            "accessControl": {
                "aws.greengrass.ipc.pubsub": {
                    "dev.txing.rig.SparkplugManager:pubsub:1": {
                        "policyDescription": (
                            "Allows Sparkplug manager to exchange v2 capability "
                            "messages with rig adapters."
                        ),
                        "operations": [
                            "aws.greengrass#PublishToTopic",
                            "aws.greengrass#SubscribeToTopic",
                        ],
                        "resources": ["dev/txing/rig/v2/*"],
                    }
                }
            },
        },
        {
            "aws.greengrass.TokenExchangeService": {
                "VersionRequirement": ">=0.0.0",
                "DependencyType": "HARD",
            }
        },
    )


def _ble_connectivity_recipe(version: str, artifact_uri: str) -> dict[str, object]:
    return _base_recipe(
        "dev.txing.rig.BleConnectivity",
        version,
        "txing rig-wide BLE connectivity adapter for power and weather devices.",
        artifact_uri,
        "\n".join(
            [
                'exec "{artifacts:path}/txing-ble-connectivity" \\',
                '  --adapter-id "{configuration:/AdapterId}" \\',
                '  --scan-interval-ms "{configuration:/ScanIntervalMs}" \\',
                '  --presence-timeout-ms "{configuration:/PresenceTimeoutMs}" \\',
                '  --reconnect-delay-ms "{configuration:/ReconnectDelayMs}" \\',
                '  --connect-timeout-ms "{configuration:/ConnectTimeoutMs}" \\',
                '  --command-timeout-ms "{configuration:/CommandTimeoutMs}" \\',
                '  --heartbeat-interval-ms "{configuration:/HeartbeatIntervalMs}" \\',
                '  --max-connections "{configuration:/MaxConnections}"',
            ]
        ),
        {
            "AdapterId": "dev.txing.rig.BleConnectivity",
            "ScanIntervalMs": 500,
            "PresenceTimeoutMs": 20000,
            "ReconnectDelayMs": 2000,
            "ConnectTimeoutMs": 8000,
            "CommandTimeoutMs": 8000,
            "HeartbeatIntervalMs": 10000,
            "MaxConnections": 0,
            "accessControl": {
                "aws.greengrass.ipc.pubsub": {
                    "dev.txing.rig.BleConnectivity:pubsub:1": {
                        "policyDescription": (
                            "Allows BLE connectivity to exchange v2 capability "
                            "messages with the Sparkplug manager."
                        ),
                        "operations": [
                            "aws.greengrass#PublishToTopic",
                            "aws.greengrass#SubscribeToTopic",
                        ],
                        "resources": ["dev/txing/rig/v2/*"],
                    }
                },
                "aws.greengrass.ipc.mqttproxy": {
                    "dev.txing.rig.BleConnectivity:mqttproxy:1": {
                        "policyDescription": (
                            "Allows BLE connectivity to publish BLE-owned named "
                            "shadow updates."
                        ),
                        "operations": ["aws.greengrass#PublishToIoTCore"],
                        "resources": [
                            "$aws/things/+/shadow/name/ble/update",
                            "$aws/things/+/shadow/name/power/update",
                            "$aws/things/+/shadow/name/weather/update",
                        ],
                    }
                },
            },
        },
    )


def _aws_connectivity_recipe(
    version: str,
    artifact_uri: str,
    aws_region: str,
    iot_data_endpoint: str,
    txing_version_base: str,
) -> dict[str, object]:
    return _base_recipe(
        "dev.txing.rig.AwsConnectivity",
        version,
        "txing rig-wide AWS retained MQTT connectivity adapter for cloud devices.",
        artifact_uri,
        "\n".join(
            [
                f'export AWS_REGION="{aws_region}"',
                f'export AWS_DEFAULT_REGION="{aws_region}"',
                f'export AWS_IOT_ENDPOINT="{iot_data_endpoint}"',
                f'export TXING_VERSION_BASE="{txing_version_base}"',
                f'export TXING_VERSION="{version}"',
                'exec "{artifacts:path}/txing-aws-connectivity" \\',
                '  --adapter-id "{configuration:/AdapterId}" \\',
                f'  --iot-endpoint "{iot_data_endpoint}" \\',
                f'  --aws-region "{aws_region}" \\',
                '  --heartbeat-interval-ms "{configuration:/HeartbeatIntervalMs}" \\',
                '  --state-report-interval-ms "{configuration:/StateReportIntervalMs}" \\',
                '  --keep-alive-seconds "{configuration:/KeepAliveSeconds}" \\',
                "  --include-capability time",
            ]
        ),
        {
            "AdapterId": "dev.txing.rig.AwsConnectivity",
            "HeartbeatIntervalMs": 10000,
            "StateReportIntervalMs": 10000,
            "KeepAliveSeconds": 60,
            "accessControl": {
                "aws.greengrass.ipc.pubsub": {
                    "dev.txing.rig.AwsConnectivity:pubsub:1": {
                        "policyDescription": (
                            "Allows AWS connectivity to exchange v2 capability "
                            "messages with the Sparkplug manager."
                        ),
                        "operations": [
                            "aws.greengrass#PublishToTopic",
                            "aws.greengrass#SubscribeToTopic",
                        ],
                        "resources": ["dev/txing/rig/v2/*"],
                    }
                }
            },
        },
        {
            "aws.greengrass.TokenExchangeService": {
                "VersionRequirement": ">=0.0.0",
                "DependencyType": "HARD",
            }
        },
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
            release = self._get_json(
                f"https://api.github.com/repos/{self.repository}/releases/latest"
            )
            tag_name = release.get("tag_name")
            if not isinstance(tag_name, str) or not tag_name:
                raise PublishError(
                    "latest GitHub release response did not include tag_name"
                )
            tag = normalize_release_tag("latest", latest_tag=tag_name)
        else:
            tag = tag_for_request
            quoted_tag = urllib.parse.quote(tag, safe="")
            release = self._get_json(
                f"https://api.github.com/repos/{self.repository}/releases/tags/{quoted_tag}"
            )
        assets = {
            asset["name"]: asset["browser_download_url"]
            for asset in release.get("assets", [])
            if asset.get("name") and asset.get("browser_download_url")
        }
        info = ReleaseInfo(tag=tag, version=tag.removeprefix("v"), assets=assets)
        self._release_cache[release_ref] = info
        self._release_cache[tag] = info
        return info

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

    def _get_json(self, url: str) -> dict[str, object]:
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
            asset_path = work_dir / asset.asset_name
            github.download_asset(release, asset.asset_name, asset_path)
            validate_lambda_zip(asset_path)
            version_key = lambda_version_key(asset.function_name, release.version)
            current_key = lambda_current_key(asset.function_name)
            _upload_file_if_missing(
                s3, config.lambda_artifact_bucket, version_key, asset_path
            )
            s3.upload_file(str(asset_path), config.lambda_artifact_bucket, current_key)
            updated = _update_lambda_function(
                lambda_client,
                asset.function_name,
                config.lambda_artifact_bucket,
                version_key,
            )
            published[asset.function_name] = {
                "versionKey": version_key,
                "currentKey": current_key,
                "updated": updated,
            }
    return {
        "releaseTag": release.tag,
        "version": release.version,
        "lambdas": published,
    }


def publish_rig(
    release_ref: str,
    config: PublishConfig | None = None,
    github: GitHubReleaseClient | None = None,
) -> dict[str, object]:
    config = config or PublishConfig.from_env()
    if not config.greengrass_artifact_bucket:
        raise PublishError("TXING_GREENGRASS_ARTIFACT_BUCKET is required")
    github = github or GitHubReleaseClient(config.github_repository)
    release = github.resolve_release(release_ref)
    s3 = boto3.client("s3")
    greengrass = boto3.client("greengrassv2")
    iot = boto3.client("iot")
    endpoint = iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
    artifacts: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="txing-rig-release.") as work_dir_raw:
        work_dir = Path(work_dir_raw)
        for component in RIG_COMPONENTS:
            asset_path = work_dir / component.asset_name
            github.download_asset(release, component.asset_name, asset_path)
            binary_path = validate_and_extract_rig_binary(
                asset_path, component.binary_name, work_dir / component.binary_name
            )
            key = rig_artifact_key(
                component.component_name, release.version, component.binary_name
            )
            _upload_file_if_missing(
                s3, config.greengrass_artifact_bucket, key, binary_path
            )
            artifacts[component.component_name] = (
                f"s3://{config.greengrass_artifact_bucket}/{key}"
            )
    created_components = []
    for component in RIG_COMPONENTS:
        recipe = greengrass_recipe(
            component.component_name,
            release.version,
            artifacts[component.component_name],
            config.aws_region,
            endpoint,
            config.txing_version_base,
        )
        _create_component_version(greengrass, recipe)
        created_components.append(component.component_name)
    deployments = {}
    for rig_type in ("raspi", "cloud"):
        target_arn = _ensure_thing_group(iot, f"txing-rig-type-{rig_type}")
        greengrass.create_deployment(
            targetArn=target_arn,
            deploymentName=f"txing-{rig_type}-{release.version}",
            components=greengrass_components_for_target(release.version, rig_type),
        )
        deployments[rig_type] = target_arn
    return {
        "releaseTag": release.tag,
        "version": release.version,
        "greengrass": {
            "components": created_components,
            "artifacts": artifacts,
            "deployments": deployments,
        },
    }


def publish_all(
    release_ref: str, config: PublishConfig | None = None
) -> dict[str, object]:
    config = config or PublishConfig.from_env()
    github = GitHubReleaseClient(config.github_repository)
    lambda_result = publish_lambdas(release_ref, config=config, github=github)
    rig_result = publish_rig(release_ref, config=config, github=github)
    return {
        "ok": True,
        "releaseTag": lambda_result["releaseTag"],
        "version": lambda_result["version"],
        "lambdas": lambda_result["lambdas"],
        "greengrass": rig_result["greengrass"],
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


def _create_component_version(greengrass, recipe: dict[str, object]) -> None:
    body = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        greengrass.create_component_version(inlineRecipe=body)
        print(
            "published component recipe "
            f"{recipe['ComponentName']} {recipe['ComponentVersion']}"
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        message = err.response.get("Error", {}).get("Message", "")
        if code == "ConflictException" or "already exists" in message.lower():
            print(
                "component recipe already exists: "
                f"{recipe['ComponentName']} {recipe['ComponentVersion']}"
            )
            return
        raise


def _ensure_thing_group(iot, group_name: str) -> str:
    try:
        iot.create_thing_group(thingGroupName=group_name)
        print(f"created thing group {group_name}")
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code != "ResourceAlreadyExistsException":
            raise
    response = iot.describe_thing_group(thingGroupName=group_name)
    return response["thingGroupArn"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aws.publish")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("lambda", "rig", "all"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--release", default="latest")
    args = parser.parse_args(argv)
    config = PublishConfig.from_env()
    if args.command == "lambda":
        result = publish_lambdas(args.release, config=config)
        result = {"ok": True, **result}
    elif args.command == "rig":
        result = publish_rig(args.release, config=config)
        result = {"ok": True, **result}
    else:
        result = publish_all(args.release, config=config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
