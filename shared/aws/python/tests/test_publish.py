from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch
import zipfile

from botocore.exceptions import ClientError, WaiterError

from aws_admin.publish_release.core import (
    GitHubReleaseClient,
    LAMBDA_ASSETS,
    PublishConfig,
    PublishError,
    ReleaseInfo,
    lambda_current_key,
    lambda_version_key,
    normalize_release_tag,
    publish_lambdas,
    validate_lambda_zip,
)
from aws_admin.publish_release.handler import lambda_handler


class _FakeGitHubReleaseClient(GitHubReleaseClient):
    def __init__(self, responses: dict[str, object]):
        super().__init__("mparkachov/txing")
        self.responses = responses
        self.requested_urls: list[str] = []

    def _get_json(self, url: str) -> object:
        self.requested_urls.append(url)
        return self.responses[url]


class PublishTests(unittest.TestCase):
    def test_normalizes_release_refs(self) -> None:
        self.assertEqual(normalize_release_tag("latest"), "latest")
        self.assertEqual(
            normalize_release_tag("latest", latest_tag="lambda-v1.2.3"),
            "lambda-v1.2.3",
        )
        self.assertEqual(normalize_release_tag("lambda-v1.2.3"), "lambda-v1.2.3")
        self.assertEqual(normalize_release_tag("v1.2.3"), "v1.2.3")
        self.assertEqual(normalize_release_tag("1.2.3"), "lambda-v1.2.3")
        with self.assertRaises(PublishError):
            normalize_release_tag("1.2")
        with self.assertRaises(PublishError):
            normalize_release_tag("release=v1.2.3")

    def test_latest_resolves_highest_lambda_prefixed_release(self) -> None:
        releases_url = "https://api.github.com/repos/mparkachov/txing/releases?per_page=100"
        github = _FakeGitHubReleaseClient(
            {
                releases_url: [
                    {"tag_name": "rig-v9.0.0", "assets": []},
                    {
                        "tag_name": "lambda-v1.2.3",
                        "assets": [{"name": "a", "browser_download_url": "https://example/a"}],
                    },
                    {
                        "tag_name": "lambda-v1.3.0",
                        "assets": [{"name": "b", "browser_download_url": "https://example/b"}],
                    },
                    {"tag_name": "unit-v8.0.0", "assets": []},
                    {"tag_name": "v99.0.0", "assets": []},
                ]
            }
        )

        release = github.resolve_release("latest")

        self.assertEqual(release.tag, "lambda-v1.3.0")
        self.assertEqual(release.version, "1.3.0")
        self.assertEqual(release.assets, {"b": "https://example/b"})
        self.assertEqual(github.requested_urls, [releases_url])

    def test_explicit_lambda_and_legacy_tags_resolve_by_tag(self) -> None:
        lambda_url = (
            "https://api.github.com/repos/mparkachov/txing/releases/tags/"
            "lambda-v1.2.3"
        )
        legacy_url = (
            "https://api.github.com/repos/mparkachov/txing/releases/tags/"
            "v1.2.3"
        )
        github = _FakeGitHubReleaseClient(
            {
                lambda_url: {"tag_name": "lambda-v1.2.3", "assets": []},
                legacy_url: {"tag_name": "v1.2.3", "assets": []},
            }
        )

        lambda_release = github.resolve_release("1.2.3")
        legacy_release = github.resolve_release("v1.2.3")

        self.assertEqual(lambda_release.tag, "lambda-v1.2.3")
        self.assertEqual(lambda_release.version, "1.2.3")
        self.assertEqual(legacy_release.tag, "v1.2.3")
        self.assertEqual(legacy_release.version, "1.2.3")

    def test_latest_requires_lambda_prefixed_release(self) -> None:
        releases_url = "https://api.github.com/repos/mparkachov/txing/releases?per_page=100"
        github = _FakeGitHubReleaseClient(
            {releases_url: [{"tag_name": "rig-v9.0.0", "assets": []}]}
        )

        with self.assertRaises(PublishError):
            github.resolve_release("latest")

    def test_expected_release_asset_names_are_stable(self) -> None:
        self.assertEqual(
            [asset.asset_name for asset in LAMBDA_ASSETS],
            [
                "txing-witness-lambda-linux-aarch64.zip",
                "txing-cloud-rig-lambda-linux-aarch64.zip",
                "txing-cloud-mcu-lambda-linux-aarch64.zip",
                "txing-virtual-quad-lambda-linux-aarch64.zip",
            ],
        )

    def test_lambda_s3_keys_match_existing_contract(self) -> None:
        self.assertEqual(
            lambda_version_key("txing-witness-lambda", "1.2.3"),
            "lambda/txing-witness-lambda/1.2.3/bootstrap.zip",
        )
        self.assertEqual(
            lambda_current_key("txing-witness-lambda"),
            "lambda/txing-witness-lambda/current/bootstrap.zip",
        )

    def test_deployed_lambda_function_names_come_from_parameter_store_contract(self) -> None:
        config = PublishConfig(
            github_repository="mparkachov/txing",
            lambda_artifact_bucket="bucket",
            aws_region="eu-central-1",
            lambda_function_names={"txing-witness-lambda": "town-witness"},
        )

        self.assertEqual(
            config.deployed_lambda_function_name(LAMBDA_ASSETS[0]),
            "town-witness",
        )

    def test_deployed_lambda_function_names_require_parameter_store_contract(self) -> None:
        config = PublishConfig(
            github_repository="mparkachov/txing",
            lambda_artifact_bucket="bucket",
            aws_region="eu-central-1",
        )

        with self.assertRaises(PublishError):
            config.deployed_lambda_function_name(LAMBDA_ASSETS[0])

    def test_validates_lambda_zip_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lambda.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("bootstrap", b"binary")
            validate_lambda_zip(path)

            bad_path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(bad_path, "w") as archive:
                archive.writestr("nested/bootstrap", b"binary")
            with self.assertRaises(PublishError):
                validate_lambda_zip(bad_path)

    def test_virtual_quad_runtime_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("bootstrap", b"binary")
                archive.writestr("quad/bin/arducopter", b"binary")
            with self.assertRaises(PublishError):
                validate_lambda_zip(path, virtual_quad=True)
            with zipfile.ZipFile(path, "w") as archive:
                for name in (
                    "bootstrap", "quad/bin/virtual-quad-supervisor",
                    "quad/bin/virtual-quad-media", "quad/bin/arducopter",
                    "quad/arducopter.parm", "quad/lib/libexample.so",
                    "quad/lib/ld-linux-aarch64.so.1", "quad/certs/starfield.pem",
                    "quad/lib/libsoftokn3.so", "quad/lib/libfreebl3.so",
                    "quad/lib/libfreeblpriv3.so",
                    "quad/plugins/libgstcoreelements.so", "quad/plugins/libgstx264.so",
                    "quad/plugins/libgstvideoparsersbad.so", "quad/plugins/libgstapp.so",
                ):
                    archive.writestr(name, b"payload")
            validate_lambda_zip(path, virtual_quad=True)
            with self.assertRaises(PublishError):
                validate_lambda_zip(path)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("quad/../escape", b"invalid")
            with self.assertRaises(PublishError):
                validate_lambda_zip(path, virtual_quad=True)

    def test_publishes_virtual_quad_runtime_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "quad.zip"
            with zipfile.ZipFile(source, "w") as archive:
                for name in (
                    "bootstrap", "quad/bin/virtual-quad-supervisor",
                    "quad/bin/virtual-quad-media", "quad/bin/arducopter",
                    "quad/arducopter.parm", "quad/lib/ld-linux-aarch64.so.1",
                    "quad/lib/libsoftokn3.so", "quad/lib/libfreebl3.so",
                    "quad/lib/libfreeblpriv3.so", "quad/certs/starfield.pem",
                    "quad/plugins/libgstcoreelements.so", "quad/plugins/libgstx264.so",
                    "quad/plugins/libgstvideoparsersbad.so", "quad/plugins/libgstapp.so",
                ):
                    archive.writestr(name, b"payload")

            asset = LAMBDA_ASSETS[-1]
            github = MagicMock()
            github.resolve_release.return_value = ReleaseInfo(
                tag="lambda-v1.2.3", version="1.2.3", assets={asset.asset_name: "url"}
            )

            def download_asset(_release, _name, path):
                path.write_bytes(source.read_bytes())

            github.download_asset.side_effect = download_asset
            s3 = MagicMock()
            s3.head_object.side_effect = ClientError(
                {"Error": {"Code": "404", "Message": "not found"}}, "HeadObject"
            )
            uploaded = {}
            s3.upload_file.side_effect = lambda path, bucket, key: uploaded.update(
                {key: (bucket, Path(path).read_bytes())}
            )
            lambda_client = MagicMock()
            config = PublishConfig(
                github_repository="mparkachov/txing", lambda_artifact_bucket="bucket",
                aws_region="eu-central-1",
                lambda_function_names={asset.artifact_id: "town-virtual-quad"},
            )
            with patch(
                "aws_admin.publish_release.core.boto3.client", side_effect=[s3, lambda_client]
            ):
                result = publish_lambdas("1.2.3", config, github, {asset.artifact_id})

            version_key = lambda_version_key(asset.artifact_id, "1.2.3")
            current_key = lambda_current_key(asset.artifact_id)
            self.assertEqual(uploaded, {
                version_key: ("bucket", source.read_bytes()),
                current_key: ("bucket", source.read_bytes()),
            })
            lambda_client.update_function_code.assert_called_once_with(
                FunctionName="town-virtual-quad", S3Bucket="bucket", S3Key=version_key
            )
            self.assertTrue(result["lambdas"][asset.artifact_id]["updated"])


class PublishUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tag = "lambda-v1.2.3"
        self.functions = {
            "txing-witness-lambda": "town-witness",
            "txing-cloud-rig-lambda": "town-cloud-rig",
            "txing-cloud-mcu-lambda": "town-cloud-mcu",
            "txing-virtual-quad-lambda": "town-virtual-quad",
        }
        self.config = PublishConfig("owner/releases", "bucket", "eu-central-1", self.functions)
        self.from_env = self.enterContext(patch.object(PublishConfig, "from_env", return_value=self.config))
        self.assets = [
            {"name": asset.asset_name, "browser_download_url": f"https://github.com/{asset.asset_name}"}
            for asset in LAMBDA_ASSETS
        ]
        self.get_json = self.enterContext(patch.object(GitHubReleaseClient, "_get_json"))
        self.get_json.return_value = [
            {"tag_name": "lambda-v1.2.2", "assets": []},
            {"tag_name": "rig-v99.0.0", "assets": []},
            {"tag_name": self.tag, "assets": self.assets},
        ]

        def write_zip(_release, _asset_name, path):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("bootstrap", b"runtime code")

        self.download_asset = self.enterContext(
            patch.object(GitHubReleaseClient, "download_asset", side_effect=write_zip)
        )
        self.s3 = MagicMock()
        self.s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        self.lambda_client = MagicMock()
        clients = {"s3": self.s3, "lambda": self.lambda_client}
        self.aws_client = self.enterContext(
            patch("aws_admin.publish_release.core.boto3.client", side_effect=clients.__getitem__)
        )

    def url_event(self, **changes) -> dict:
        return {
            "version": "2.0",
            "rawPath": "/",
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps({"release": self.tag}),
            "isBase64Encoded": False,
            **changes,
        }

    def test_publishes_current_release_and_waits_for_all_updates(self) -> None:
        response = lambda_handler(self.url_event(), None)

        self.assertEqual(response["statusCode"], 200)
        result = json.loads(response["body"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["releaseTag"], self.tag)
        self.assertEqual(set(result["lambdas"]), set(self.functions))
        self.get_json.assert_called_once_with("https://api.github.com/repos/owner/releases/releases?per_page=100")
        self.assertEqual(self.download_asset.call_count, 4)
        self.assertEqual(self.s3.upload_file.call_count, 8)
        self.assertEqual(
            self.lambda_client.update_function_code.call_args_list,
            [
                call(FunctionName=name, S3Bucket="bucket", S3Key=lambda_version_key(artifact, "1.2.3"))
                for artifact, name in self.functions.items()
            ],
        )
        self.assertEqual(
            self.lambda_client.get_waiter.return_value.wait.call_args_list,
            [call(FunctionName=name) for name in self.functions.values()],
        )
        self.assertTrue(all(item["updated"] for item in result["lambdas"].values()))

    def test_rejects_invalid_requests_before_loading_configuration(self) -> None:
        for status, changes in (
            (404, {"rawPath": "/unused"}),
            (405, {"requestContext": {"http": {"method": "GET"}}}),
            (400, {"body": "{"}),
            (400, {"body": "null"}),
            (400, {"body": '{"release":"latest"}'}),
            (400, {"body": '{"release":"v1.2.3"}'}),
            (400, {"body": '{"release":"lambda-v1.2.3","repository":"owner/other"}'}),
            (400, {"isBase64Encoded": True}),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(lambda_handler(self.url_event(**changes), None)["statusCode"], status)

        self.from_env.assert_not_called()

    def test_rejects_stale_release_before_accessing_aws(self) -> None:
        response = lambda_handler(self.url_event(body='{"release":"lambda-v1.2.2"}'), None)

        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["releaseTag"], self.tag)
        self.download_asset.assert_not_called()
        self.aws_client.assert_not_called()

    def test_fails_before_writes_if_the_release_is_missing_an_asset(self) -> None:
        self.assets.pop()

        with self.assertLogs("aws_admin.publish_release.handler", level="ERROR"):
            response = lambda_handler(self.url_event(), None)

        self.assertEqual(response["statusCode"], 500)
        self.aws_client.assert_not_called()

    def test_fails_if_a_runtime_function_is_missing(self) -> None:
        self.lambda_client.get_function.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException"}}, "GetFunction"
        )

        with self.assertLogs("aws_admin.publish_release.handler", level="ERROR"):
            response = lambda_handler(self.url_event(), None)

        self.assertEqual(response["statusCode"], 500)
        self.lambda_client.update_function_code.assert_not_called()

    def test_fails_if_an_aws_code_update_does_not_succeed(self) -> None:
        self.lambda_client.get_waiter.return_value.wait.side_effect = WaiterError(
            name="function_updated", reason="UpdateFailed", last_response={}
        )

        with self.assertLogs("aws_admin.publish_release.handler", level="ERROR"):
            response = lambda_handler(self.url_event(), None)

        self.assertEqual(response["statusCode"], 500)
        self.lambda_client.update_function_code.assert_called_once()

    def test_direct_invocation_still_accepts_a_legacy_release_ref(self) -> None:
        with patch("aws_admin.publish_release.handler.publish_all") as publish:
            response = lambda_handler({"release": "v1.2.2"}, None)

        publish.assert_called_once_with("v1.2.2", config=self.config)
        self.assertIs(response, publish.return_value)


if __name__ == "__main__":
    unittest.main()
