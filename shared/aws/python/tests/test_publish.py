from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from botocore.exceptions import ClientError

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


if __name__ == "__main__":
    unittest.main()
