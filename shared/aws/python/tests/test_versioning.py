from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


class VersionEnvironmentTests(unittest.TestCase):
    def test_project_version_env_uses_plain_version_and_reports_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            root_justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
            version_recipe = root_justfile.split("\n[private]\n_project-aws-env", 1)[0]
            (repo / "justfile").write_text(version_recipe, encoding="utf-8")
            (repo / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "add", "VERSION", "justfile"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )

            clean = subprocess.run(
                ["just", "--justfile", str(repo / "justfile"), "_project-version-env"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertIn("export TXING_VERSION=1.2.3", clean)
            self.assertIn("export TXING_GIT_DIRTY=false", clean)

            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(
                ["just", "--justfile", str(repo / "justfile"), "_project-version-env"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertIn("export TXING_VERSION=1.2.3", dirty)
            self.assertIn("export TXING_GIT_DIRTY=true", dirty)
            self.assertNotIn("+g", dirty)

    def test_rig_deploy_defaults_to_project_release_and_immutable_artifacts(self) -> None:
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")

        self.assertIn("deploy target='auto'", rig_justfile)
        self.assertIn("check-greengrass-lite", rig_justfile)
        self.assertNotIn("git clone --branch", rig_justfile)
        self.assertNotIn("TXING_RIG_GREENGRASS_LITE_REPOSITORY", rig_justfile)
        self.assertIn('env_scope="rig"', rig_justfile)
        self.assertIn('deploy_target="$RIG_TYPE"', rig_justfile)
        self.assertIn('resolved_component_version="$TXING_VERSION"', rig_justfile)
        self.assertIn("Refusing production Greengrass deploy from a dirty worktree.", rig_justfile)
        self.assertNotIn("TXING_ALLOW_DIRTY_DEPLOY", rig_justfile)
        self.assertNotIn("TXING_RIG_ALLOW_DIRTY_DEPLOY", rig_justfile)
        self.assertNotIn("_check-rig-cargo-version", rig_justfile)
        self.assertIn('local key="artifacts/$component/$resolved_component_version/$filename"', rig_justfile)
        self.assertIn("aws s3api head-object", rig_justfile)
        self.assertNotIn("artifact_version_path", rig_justfile)

    def test_stable_release_publishes_only_project_assets(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "unit-daemon-stable-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: Txing Stable Release", workflow)
        self.assertIn("txing-unit-daemon-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-sparkplug-manager-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-ble-connectivity-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-aws-connectivity-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-rig-deploy-linux-aarch64.tar.gz", workflow)
        self.assertIn('version="$(tr -d \'[:space:]\' < VERSION)"', workflow)
        self.assertIn("git fetch --tags --force origin", workflow)
        self.assertIn("Pushed VERSION $version must be greater than latest stable tag", workflow)
        self.assertIn('release_target="$(git rev-parse HEAD)"', workflow)
        self.assertIn("python3 release/src/txing_release/cli.py check", workflow)
        self.assertNotIn("txing-greengrass-lite-linux-aarch64.tar.gz", workflow)
        self.assertNotIn("Build Greengrass Lite", workflow)
        self.assertNotIn("Package Greengrass Lite release asset", workflow)
        self.assertNotIn("Publish Greengrass Lite release", workflow)
        self.assertNotIn("greengrass_lite_version", workflow)
        self.assertNotIn("greengrass-lite-v", workflow)
        self.assertNotIn("modules/aws-greengrass/aws-greengrass-lite/version", workflow)
        self.assertNotIn("txing-greengrass-lite-payload/root", workflow)
        self.assertNotIn('run_nucleus "$payload_dir', workflow)
        self.assertNotIn("description: \"Stable version to release", workflow)
        self.assertNotIn("inputs:", workflow)
        self.assertNotIn("VERSION_INPUT", workflow)
        self.assertNotIn("next-minor-default", workflow)
        self.assertNotIn("workflow-input", workflow)
        self.assertNotIn("release/src/txing_release/cli.py bump", workflow)
        self.assertNotIn("Commit release bump", workflow)
        self.assertNotIn("git push origin", workflow)
        self.assertNotIn("greengrass-lite-version", workflow)
        self.assertNotIn("TXING_GREENGRASS_LITE_BUILD_INPUT_HASH", workflow)

    def test_rig_mise_config_uses_github_assets_and_greengrass_prefix(self) -> None:
        installer = (REPO_ROOT / "rig" / "install-mise-tools.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('txing-sparkplug-manager = "github:$owner/$repo"', installer)
        self.assertIn('txing-ble-connectivity = "github:$owner/$repo"', installer)
        self.assertIn('txing-aws-connectivity = "github:$owner/$repo"', installer)
        self.assertIn('txing-rig-deploy = "github:$owner/$repo"', installer)
        self.assertIn(
            'txing-greengrass-lite = "github:aws-greengrass/aws-greengrass-lite"',
            installer,
        )
        self.assertIn(
            'asset_pattern = "txing-rig-deploy-linux-aarch64.tar.gz"', installer
        )
        self.assertIn(
            'asset_pattern = "aws-greengrass-lite-deb-arm64.zip"',
            installer,
        )
        self.assertNotIn('version_prefix = "greengrass-lite-v"', installer)
        self.assertNotIn("prerelease = true", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("run as root", installer)
        self.assertNotIn("chown", installer)

    def test_greengrass_lite_submodule_stays_top_level_module(self) -> None:
        self.assertFalse((REPO_ROOT / "rig" / "greengrass-lite-build.env").exists())
        self.assertFalse(
            (REPO_ROOT / "rig" / "scripts" / "greengrass-lite-version").exists()
        )

        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn('[submodule "aws-greengrass/aws-greengrass-lite"]', gitmodules)
        self.assertIn(
            "path = modules/aws-greengrass/aws-greengrass-lite", gitmodules
        )
        self.assertIn(
            '[submodule "awslabs/amazon-kinesis-video-streams-webrtc-sdk-c"]',
            gitmodules,
        )
        self.assertIn(
            "path = modules/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c",
            gitmodules,
        )
        self.assertIn('[submodule "nrfconnect/sdk-nrf"]', gitmodules)
        self.assertIn("path = modules/nrfconnect/sdk-nrf", gitmodules)
        self.assertIn("branch = main", gitmodules)

    def test_greengrass_lite_helper_removed(self) -> None:
        self.assertFalse((REPO_ROOT / "rig" / "scripts" / "txing-greengrass-lite").exists())

    def test_rig_deploy_dry_run_generates_expected_recipes(self) -> None:
        script = REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installs = root / "installs"
            version = "1.2.3"
            binary_paths = {}
            for tool in (
                "txing-sparkplug-manager",
                "txing-ble-connectivity",
                "txing-aws-connectivity",
            ):
                binary_dir = installs / tool / version
                if tool == "txing-aws-connectivity":
                    binary_dir = binary_dir / "bin"
                binary = binary_dir / tool
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o755)
                binary_paths[tool] = binary

            out_dir = root / "dry-run"
            env = os.environ.copy()
            env.update(
                {
                    "TXING_RIG_DEPLOY_DRY_RUN": "true",
                    "TXING_RIG_DEPLOY_DRY_RUN_DIR": str(out_dir),
                    "TXING_SPARKPLUG_MANAGER_BINARY": str(
                        binary_paths["txing-sparkplug-manager"]
                    ),
                    "TXING_BLE_CONNECTIVITY_BINARY": str(
                        binary_paths["txing-ble-connectivity"]
                    ),
                    "TXING_AWS_CONNECTIVITY_BINARY": str(
                        binary_paths["txing-aws-connectivity"]
                    ),
                    "RIG_TYPE": "raspi",
                    "AWS_REGION": "eu-central-1",
                    "AWS_STACK_NAME": "town",
                }
            )
            subprocess.run([str(script), "auto"], check=True, env=env, text=True)

            sparkplug_recipe = (
                out_dir / "recipes" / "dev.txing.rig.SparkplugManager.yaml"
            ).read_text(encoding="utf-8")
            ble_recipe = (
                out_dir / "recipes" / "dev.txing.rig.BleConnectivity.yaml"
            ).read_text(encoding="utf-8")
            aws_recipe = (
                out_dir / "recipes" / "dev.txing.rig.AwsConnectivity.yaml"
            ).read_text(encoding="utf-8")

            self.assertIn("ComponentVersion: '1.2.3'", sparkplug_recipe)
            self.assertIn(
                "artifacts/dev.txing.rig.SparkplugManager/1.2.3/txing-sparkplug-manager",
                sparkplug_recipe,
            )
            self.assertIn("aws.greengrass#PublishToTopic", ble_recipe)
            self.assertIn("txing-aws-connectivity", aws_recipe)

    def test_rig_deploy_rejects_version_skew(self) -> None:
        script = REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            versions = {
                "txing-sparkplug-manager": "1.2.3",
                "txing-ble-connectivity": "1.2.4",
                "txing-aws-connectivity": "1.2.3",
            }
            env = os.environ.copy()
            env.update(
                {
                    "TXING_RIG_DEPLOY_DRY_RUN": "true",
                    "RIG_TYPE": "raspi",
                    "AWS_REGION": "eu-central-1",
                    "AWS_STACK_NAME": "town",
                }
            )
            for tool, version in versions.items():
                binary = root / "installs" / tool / version / tool
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o755)
                env_name = {
                    "txing-sparkplug-manager": "TXING_SPARKPLUG_MANAGER_BINARY",
                    "txing-ble-connectivity": "TXING_BLE_CONNECTIVITY_BINARY",
                    "txing-aws-connectivity": "TXING_AWS_CONNECTIVITY_BINARY",
                }[tool]
                env[env_name] = str(binary)

            result = subprocess.run(
                [str(script), "raspi"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("version skew", result.stderr)

    def test_release_version_is_manual(self) -> None:
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "release-version.yml").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "release_version.py").exists())


if __name__ == "__main__":
    unittest.main()
