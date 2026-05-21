from __future__ import annotations

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from aws_admin.publish_release.core import (
    GREENGRASS_COMPONENT_VERSIONS_TO_KEEP,
    LAMBDA_ASSETS,
    RIG_COMPONENTS,
    PublishError,
    cleanup_greengrass_component_versions,
    greengrass_components_for_target,
    greengrass_component_versions_to_delete,
    greengrass_recipe,
    lambda_current_key,
    lambda_version_key,
    normalize_release_tag,
    rig_artifact_key,
    validate_and_extract_rig_binary,
    validate_lambda_zip,
    _ensure_thing_group,
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
        self.assertEqual(
            [component.asset_name for component in RIG_COMPONENTS],
            [
                "txing-sparkplug-manager-linux-aarch64.tar.gz",
                "txing-ble-connectivity-linux-aarch64.tar.gz",
                "txing-aws-connectivity-linux-aarch64.tar.gz",
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

    def test_rig_s3_key_matches_existing_contract(self) -> None:
        self.assertEqual(
            rig_artifact_key(
                "dev.txing.rig.SparkplugManager",
                "1.2.3",
                "txing-sparkplug-manager",
            ),
            "artifacts/dev.txing.rig.SparkplugManager/1.2.3/txing-sparkplug-manager",
        )

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

    def test_validates_and_extracts_root_level_rig_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "rig.tar.gz"
            payload = b"binary"
            info = tarfile.TarInfo("txing-sparkplug-manager")
            info.size = len(payload)
            info.mode = 0o755
            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.addfile(info, io.BytesIO(payload))

            extracted = validate_and_extract_rig_binary(
                archive_path,
                "txing-sparkplug-manager",
                Path(tmp) / "out",
            )
            self.assertEqual(extracted.read_bytes(), payload)

    def test_rejects_nested_rig_tarball_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "rig.tar.gz"
            payload = b"binary"
            info = tarfile.TarInfo("bin/txing-sparkplug-manager")
            info.size = len(payload)
            info.mode = 0o755
            with tarfile.open(archive_path, mode="w:gz") as archive:
                archive.addfile(info, io.BytesIO(payload))

            with self.assertRaises(PublishError):
                validate_and_extract_rig_binary(
                    archive_path,
                    "txing-sparkplug-manager",
                    Path(tmp) / "out",
                )

    def test_greengrass_all_target_component_maps(self) -> None:
        self.assertEqual(
            greengrass_components_for_target("1.2.3", "raspi"),
            {
                "dev.txing.rig.SparkplugManager": {"componentVersion": "1.2.3"},
                "dev.txing.rig.BleConnectivity": {"componentVersion": "1.2.3"},
            },
        )
        self.assertEqual(
            greengrass_components_for_target("1.2.3", "cloud"),
            {
                "dev.txing.rig.SparkplugManager": {"componentVersion": "1.2.3"},
                "dev.txing.rig.AwsConnectivity": {"componentVersion": "1.2.3"},
            },
        )

    def test_greengrass_recipe_generation_uses_structured_recipes(self) -> None:
        recipe = greengrass_recipe(
            "dev.txing.rig.AwsConnectivity",
            "1.2.3",
            "s3://bucket/artifacts/dev.txing.rig.AwsConnectivity/1.2.3/txing-aws-connectivity",
            "eu-central-1",
            "example.iot.eu-central-1.amazonaws.com",
            "1.2.3",
        )
        self.assertEqual(recipe["RecipeFormatVersion"], "2020-01-25")
        self.assertEqual(recipe["ComponentName"], "dev.txing.rig.AwsConnectivity")
        self.assertEqual(recipe["ComponentVersion"], "1.2.3")
        self.assertIn("aws.greengrass.TokenExchangeService", recipe["ComponentDependencies"])
        manifest = recipe["Manifests"][0]
        self.assertEqual(manifest["Platform"]["runtime"], "aws_nucleus_lite")
        self.assertIn("txing-aws-connectivity", manifest["Lifecycle"]["run"]["Script"])
        self.assertEqual(
            manifest["Artifacts"][0]["Uri"],
            "s3://bucket/artifacts/dev.txing.rig.AwsConnectivity/1.2.3/txing-aws-connectivity",
        )

    def test_ensure_thing_group_reads_top_level_arn_from_boto3_response(self) -> None:
        class FakeIot:
            def __init__(self) -> None:
                self.created_groups: list[str] = []

            def create_thing_group(self, *, thingGroupName: str) -> None:
                self.created_groups.append(thingGroupName)

            def describe_thing_group(self, *, thingGroupName: str) -> dict[str, object]:
                return {
                    "thingGroupName": thingGroupName,
                    "thingGroupArn": (
                        "arn:aws:iot:eu-central-1:123456789012:"
                        f"thinggroup/{thingGroupName}"
                    ),
                    "thingGroupMetadata": {},
                }

        iot = FakeIot()
        self.assertEqual(
            _ensure_thing_group(iot, "txing-rig-type-raspi"),
            "arn:aws:iot:eu-central-1:123456789012:thinggroup/txing-rig-type-raspi",
        )
        self.assertEqual(iot.created_groups, ["txing-rig-type-raspi"])

    def test_greengrass_component_cleanup_keeps_newest_10_semver_versions(self) -> None:
        versions = [
            {
                "componentVersion": f"1.0.{patch}",
                "arn": (
                    "arn:aws:greengrass:eu-central-1:123456789012:"
                    f"components/dev.txing.rig.SparkplugManager/versions/1.0.{patch}"
                ),
            }
            for patch in range(12)
        ]

        delete = greengrass_component_versions_to_delete(
            versions, keep_versions=GREENGRASS_COMPONENT_VERSIONS_TO_KEEP
        )

        self.assertEqual(
            [version["componentVersion"] for version in delete],
            ["1.0.1", "1.0.0"],
        )

    def test_greengrass_component_cleanup_deletes_only_old_txing_versions(self) -> None:
        class FakePaginator:
            def __init__(self, pages: list[dict[str, object]]) -> None:
                self.pages = pages

            def paginate(self, **kwargs: object):
                yield from self.pages

        class FakeGreengrass:
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def get_paginator(self, operation: str) -> FakePaginator:
                if operation == "list_components":
                    return FakePaginator(
                        [
                            {
                                "components": [
                                    {
                                        "componentName": "dev.txing.rig.SparkplugManager",
                                        "arn": "component-arn",
                                    },
                                    {
                                        "componentName": "unrelated",
                                        "arn": "unrelated-arn",
                                    },
                                ]
                            }
                        ]
                    )
                if operation == "list_component_versions":
                    return FakePaginator(
                        [
                            {
                                "componentVersions": [
                                    {
                                        "componentVersion": f"2.0.{patch}",
                                        "arn": f"component-version-arn-{patch}",
                                    }
                                    for patch in range(11)
                                ]
                            }
                        ]
                    )
                raise AssertionError(operation)

            def delete_component(self, *, arn: str) -> None:
                self.deleted.append(arn)

        greengrass = FakeGreengrass()

        result = cleanup_greengrass_component_versions(
            greengrass,
            ["dev.txing.rig.SparkplugManager", "dev.txing.rig.BleConnectivity"],
        )

        self.assertEqual(
            result,
            {
                "dev.txing.rig.SparkplugManager": ["2.0.0"],
                "dev.txing.rig.BleConnectivity": [],
            },
        )
        self.assertEqual(greengrass.deleted, ["component-version-arn-0"])


if __name__ == "__main__":
    unittest.main()
