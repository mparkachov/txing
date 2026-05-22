from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from aws_admin.publish_release.core import (
    LAMBDA_ASSETS,
    PublishConfig,
    PublishError,
    lambda_current_key,
    lambda_version_key,
    normalize_release_tag,
    validate_lambda_zip,
)


class PublishTests(unittest.TestCase):
    def test_normalizes_release_refs(self) -> None:
        self.assertEqual(normalize_release_tag("latest"), "latest")
        self.assertEqual(normalize_release_tag("latest", latest_tag="v1.2.3"), "v1.2.3")
        self.assertEqual(normalize_release_tag("v1.2.3"), "v1.2.3")
        self.assertEqual(normalize_release_tag("1.2.3"), "v1.2.3")
        with self.assertRaises(PublishError):
            normalize_release_tag("1.2")
        with self.assertRaises(PublishError):
            normalize_release_tag("release=v1.2.3")

    def test_expected_release_asset_names_are_stable(self) -> None:
        self.assertEqual(
            [asset.asset_name for asset in LAMBDA_ASSETS],
            [
                "txing-witness-lambda-linux-aarch64.zip",
                "txing-cloud-rig-lambda-linux-aarch64.zip",
                "txing-cloud-mcu-lambda-linux-aarch64.zip",
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


if __name__ == "__main__":
    unittest.main()
