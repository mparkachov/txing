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
        self.assertIn("deploy-release release='latest' target='all'", rig_justfile)
        self.assertIn('_project-aws-env aws "{{region}}" "{{aws_profile}}"', rig_justfile)
        self.assertIn('export TXING_RIG_ENV_FILE="$AWS_ENV_FILE"', rig_justfile)
        self.assertIn('scripts/txing-rig-deploy-release" "{{release}}" "{{target}}"', rig_justfile)

    def test_stable_release_publishes_only_project_assets(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "unit-daemon-stable-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: Txing Stable Release", workflow)
        self.assertIn("Install mise tools", workflow)
        self.assertIn("curl https://mise.run | sh", workflow)
        self.assertIn("mise/shims", workflow)
        self.assertIn("use --global --yes uv@latest just@latest", workflow)
        self.assertIn("txing-unit-daemon-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-board-kvs-master-linux-aarch64.tar.gz", workflow)
        self.assertIn("KVS_MASTER_BUILD_IMAGE: debian:trixie", workflow)
        self.assertIn("KVS_MASTER_BINARY: txing-board-kvs-master", workflow)
        self.assertIn("Build native KVS master in Trixie container", workflow)
        self.assertIn("docker run --rm -i", workflow)
        self.assertIn("just unit::board::build-native", workflow)
        self.assertIn("URIs: https://archive.raspberrypi.com/debian/", workflow)
        self.assertIn("Trusted: yes", workflow)
        self.assertIn("apt-cache policy libcamera-dev libcamera0.7", workflow)
        self.assertIn(
            'git config --global --add safe.directory "$PWD/modules/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c"',
            workflow,
        )
        self.assertIn('grep -F "libcamera.so.0.7"', workflow)
        self.assertIn('grep -F "libcamera-base.so.0.7"', workflow)
        self.assertIn('kvs_master_build_binary="devices/unit/board/kvs_master/build/$KVS_MASTER_BINARY"', workflow)
        self.assertIn('test -x "$kvs_master_build_binary"', workflow)
        self.assertIn('install -m 755 "$kvs_master_build_binary" "$RUNNER_TEMP/$KVS_MASTER_BINARY"', workflow)
        self.assertIn('package_binary "$RUNNER_TEMP/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("KVS_MASTER_OUTPUT_DIR", workflow)
        self.assertNotIn('-v "$RUNNER_TEMP:/out"', workflow)
        self.assertNotIn('"/out/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("raspberrypi.gpg.key", workflow)
        self.assertNotIn("Signed-By:", workflow)
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
        self.assertNotIn("curl git just", workflow)
        self.assertNotIn("JUST_VERSION", workflow)
        self.assertNotIn("cargo install just", workflow)
        self.assertNotIn("pip install --user uv", workflow)

    def test_unit_daemon_feature_prerelease_publishes_daemon_and_kvs_master(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "unit-daemon-feature-prerelease.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: Unit Daemon Feature Prerelease", workflow)
        self.assertIn("UNIT_DAEMON_ASSET: txing-unit-daemon-linux-aarch64.tar.gz", workflow)
        self.assertIn("KVS_MASTER_ASSET: txing-board-kvs-master-linux-aarch64.tar.gz", workflow)
        self.assertIn("KVS_MASTER_BUILD_IMAGE: debian:trixie", workflow)
        self.assertIn("Install mise tools", workflow)
        self.assertIn("curl https://mise.run | sh", workflow)
        self.assertIn("mise/shims", workflow)
        self.assertIn("use --global --yes uv@latest just@latest", workflow)
        self.assertIn("Build native KVS master in Trixie container", workflow)
        self.assertIn("docker run --rm -i", workflow)
        self.assertIn("just unit::board::build-native", workflow)
        self.assertIn("URIs: https://archive.raspberrypi.com/debian/", workflow)
        self.assertIn("Trusted: yes", workflow)
        self.assertIn("apt-cache policy libcamera-dev libcamera0.7", workflow)
        self.assertIn(
            'git config --global --add safe.directory "$PWD/modules/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c"',
            workflow,
        )
        self.assertIn('grep -F "libcamera.so.0.7"', workflow)
        self.assertIn('grep -F "libcamera-base.so.0.7"', workflow)
        self.assertIn('kvs_master_build_binary="devices/unit/board/kvs_master/build/$KVS_MASTER_BINARY"', workflow)
        self.assertIn('test -x "$kvs_master_build_binary"', workflow)
        self.assertIn('install -m 755 "$kvs_master_build_binary" "$RUNNER_TEMP/$KVS_MASTER_BINARY"', workflow)
        self.assertIn('package_binary "$RUNNER_TEMP/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("KVS_MASTER_OUTPUT_DIR", workflow)
        self.assertNotIn('-v "$RUNNER_TEMP:/out"', workflow)
        self.assertNotIn('"/out/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("raspberrypi.gpg.key", workflow)
        self.assertNotIn("Signed-By:", workflow)
        self.assertIn('"$UNIT_DAEMON_ASSET_PATH" "$KVS_MASTER_ASSET_PATH"', workflow)
        self.assertNotIn("ASSET_NAME: txing-unit-daemon", workflow)
        self.assertNotIn("curl git just", workflow)
        self.assertNotIn("JUST_VERSION", workflow)
        self.assertNotIn("cargo install just", workflow)

    def test_unit_daemon_root_owned_installer_uses_mise_for_daemon_and_kvs_master(self) -> None:
        installer = (
            REPO_ROOT / "devices" / "unit" / "daemon" / "install-systemd.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("root-owned txing unit daemon systemd service", installer)
        self.assertIn("run this installer from a root shell", installer)
        self.assertIn('txing-unit-daemon = "github:mparkachov/txing"', installer)
        self.assertIn('txing-board-kvs-master = "github:mparkachov/txing"', installer)
        self.assertIn('asset_pattern = "$daemon_asset_pattern"', installer)
        self.assertIn('asset_pattern = "$kvs_master_asset_pattern"', installer)
        self.assertIn("txing-board-kvs-master-linux-aarch64.tar.gz", installer)
        self.assertIn('fetch_remote_versions_cache = "10m"', installer)
        self.assertIn('root_home="${TXING_DAEMON_ROOT_HOME:-${HOME:-/root}}"', installer)
        self.assertIn('daemon_config_dir="${TXING_DAEMON_CONFIG_DIR:-$root_home/.config/txing/unit-daemon}"', installer)
        self.assertIn('mise_data_dir="$root_home/.local/share/mise"', installer)
        self.assertIn("Environment=HOME=$root_home", installer)
        self.assertIn("Environment=TXING_KVS_MASTER_COMMAND=$kvs_master_binary", installer)
        self.assertIn("run_root_mise install --force txing-unit-daemon@latest txing-board-kvs-master@latest", installer)
        self.assertIn("run_feature_mise install --force txing-unit-daemon@latest txing-board-kvs-master@latest", installer)
        self.assertIn('daemon_binary="$(run_root_mise which txing-unit-daemon)"', installer)
        self.assertIn('daemon_binary="$(run_feature_mise which txing-unit-daemon)"', installer)
        self.assertIn('kvs_master_binary="$(run_feature_mise which txing-board-kvs-master)"', installer)
        self.assertIn('check_shared_libraries "txing-board-kvs-master" "$kvs_master_binary"', installer)
        self.assertIn("unresolved shared libraries", installer)
        self.assertIn("libcamera.so.0.7", installer)
        self.assertIn("libcamera.so.0.2", installer)
        self.assertIn("libcamera.so.0.4", installer)
        self.assertIn("StartLimitBurst=5", installer)
        self.assertIn("MISE_DATA_DIR=$mise_data_dir", installer)
        self.assertNotIn("MISE_SHARED_INSTALL_DIRS", installer)
        self.assertIn("MISE_TRUSTED_CONFIG_PATHS=$mise_config_root", installer)
        self.assertIn('feature_trusted_config_paths="$mise_config_root:$mise_config_dir"', installer)
        self.assertIn("MISE_TRUSTED_CONFIG_PATHS=$feature_trusted_config_paths", installer)
        self.assertIn("ExecStartPre=/usr/bin/test -x $daemon_binary", installer)
        self.assertIn("ExecStartPre=/usr/bin/test -x $kvs_master_binary", installer)
        self.assertIn("ExecStartPre=/usr/bin/echo txing-unit-daemon binary: $daemon_binary", installer)
        self.assertIn("ExecStartPre=-$daemon_binary --version", installer)
        self.assertIn("ExecStartPre=/usr/bin/echo txing-board-kvs-master binary: $kvs_master_binary", installer)
        self.assertIn("ExecStart=$daemon_binary", installer)
        self.assertIn("daemon version:", installer)
        self.assertIn("does not support --version", installer)
        self.assertNotIn("ExecStart=/usr/bin/env MISE_OFFLINE=1", installer)
        self.assertIn('install -m 644 "$service_tmp" "$service_file"', installer)
        self.assertIn('systemctl reset-failed "$service_name"', installer)
        self.assertIn('systemctl restart "$service_name"', installer)
        self.assertIn("$daemon_config_dir/daemon.env", installer)
        self.assertIn("warning: daemon runtime config is not readable yet", installer)
        self.assertIn("warning: daemon private key is not readable yet", installer)
        self.assertNotIn("missing daemon runtime config", installer)
        self.assertNotIn("missing daemon private key", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("runuser", installer)
        self.assertNotIn("chown", installer)
        self.assertNotIn("/home/txing/.local/share/mise", installer)
        self.assertNotIn("generated_systemd_dir", installer)

    def test_board_stable_docs_use_daemon_kvs_master_release_path(self) -> None:
        installation_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )
        artifacts_docs = (REPO_ROOT / "docs" / "artifacts.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("mise which txing-board-kvs-master", installation_docs)
        self.assertIn("bash /tmp/txing-install-systemd.sh stable", installation_docs)
        self.assertIn("sudo su -", installation_docs)
        self.assertIn("/root/.local/bin/mise which txing-board-kvs-master", installation_docs)
        self.assertIn("just unit::daemon::role-policy <thing-id>", installation_docs)
        self.assertIn("MQTT-only `mcp`", installation_docs)
        self.assertIn("just unit::daemon::role-policy <thing-id>", artifacts_docs)
        self.assertIn("Use this path for Phase 2a board iteration", artifacts_docs)
        self.assertIn("txing-board-kvs-master-linux-aarch64.tar.gz", artifacts_docs)
        self.assertIn("TXING_KVS_MASTER_COMMAND", artifacts_docs)
        self.assertIn("daemon.env", installation_docs)
        self.assertIn("daemon.env", artifacts_docs)
        self.assertIn("Raspberry Pi OS apt repository", artifacts_docs)
        self.assertIn("libcamera.so.0.7", installation_docs)
        self.assertIn("libcamera.so.0.7", artifacts_docs)
        self.assertIn("libcamera.so.0.2", installation_docs)
        self.assertIn("libcamera.so.0.4", installation_docs)
        self.assertIn("installer runs `ldd`", installation_docs)
        self.assertIn("installer runs `ldd`", artifacts_docs)
        self.assertIn("mount /tmp ; mount /var/tmp", installation_docs)
        self.assertIn("MISE_DATA_DIR=/root/.local/share/mise", artifacts_docs)
        self.assertIn("service starts offline", artifacts_docs)
        self.assertIn("bash /tmp/txing-install-systemd.sh feature", artifacts_docs)
        self.assertNotIn("install-systemd.sh | sudo bash", installation_docs)
        self.assertNotIn("install-systemd.sh | sudo bash", artifacts_docs)
        self.assertNotIn("MISE_SHARED_INSTALL_DIRS", artifacts_docs)
        self.assertNotIn("sudo -u txing env HOME=/home/txing", installation_docs)
        self.assertNotIn("sudo -u txing env HOME=/home/txing", artifacts_docs)
        self.assertNotIn("mise-txing-unit-daemon-feature", artifacts_docs)
        self.assertNotIn("BOARD_VIDEO_SENDER_COMMAND", installation_docs)
        self.assertNotIn("just unit::board::build-native", installation_docs)
        self.assertNotIn("sudo systemctl status board", installation_docs)
        self.assertNotIn("git clone <repo-url>", installation_docs)
        self.assertNotIn("$TXING_HOME", installation_docs)

    def test_rig_mise_config_uses_github_assets_without_greengrass(self) -> None:
        installer = (REPO_ROOT / "rig" / "install-mise-tools.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('txing-sparkplug-manager = "github:$owner/$repo"', installer)
        self.assertIn('txing-ble-connectivity = "github:$owner/$repo"', installer)
        self.assertIn('txing-aws-connectivity = "github:$owner/$repo"', installer)
        self.assertIn('txing-rig-deploy = "github:$owner/$repo"', installer)
        self.assertIn('[settings]', installer)
        self.assertIn('fetch_remote_versions_cache = "0s"', installer)
        self.assertIn(
            'asset_pattern = "txing-rig-deploy-linux-aarch64.tar.gz"', installer
        )
        self.assertNotIn("txing-greengrass-lite", installer)
        self.assertNotIn("aws-greengrass-lite-deb-arm64.zip", installer)
        self.assertNotIn('version_prefix = "greengrass-lite-v"', installer)
        self.assertNotIn("prerelease = true", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("run as root", installer)
        self.assertNotIn("chown", installer)

    def test_rig_ble_component_runs_without_greengrass_privilege(self) -> None:
        stable_deploy = (REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy").read_text(
            encoding="utf-8"
        )
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")
        rig_docs = (REPO_ROOT / "docs" / "components" / "rig.md").read_text(
            encoding="utf-8"
        )
        installation_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("txing-ble-connectivity", stable_deploy)
        self.assertTrue((REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy-release").exists())
        self.assertNotIn("RequiresPrivilege: true", stable_deploy)
        self.assertNotIn("RequiresPrivilege: true", rig_justfile)
        self.assertIn("Canonical rig installation", installation_docs)
        self.assertIn("components/rig.md", installation_docs)
        self.assertIn("gg_component", rig_docs)
        self.assertIn("bluetooth", rig_docs)
        self.assertIn("aws-greengrass-lite-deb-arm64.zip", rig_docs)
        self.assertIn("aws-greengrass-lite-$GGL_VERSION-Linux.deb", rig_docs)
        self.assertIn("Transfer these files from `config/certs/rig/`", rig_docs)
        self.assertIn("already contains the rig thing name", rig_docs)
        self.assertIn("just aws::greengrass-config <rig-id>", rig_docs)
        self.assertIn('GGL_CONFIG="./greengrass-lite.yaml"', rig_docs)
        self.assertIn("/etc/greengrass/config.d/greengrass-lite.yaml", rig_docs)
        self.assertIn("/var/lib/greengrass/credentials/", rig_docs)
        self.assertIn("just rig::deploy-release latest all", rig_docs)
        self.assertIn("The rig does not run AWS CLI", rig_docs)
        self.assertIn("A stable rig does not need", rig_docs)
        self.assertIn("a repo checkout, mise, AWS CLI", rig_docs)
        self.assertNotIn("mise use --global aws-cli@latest gh@latest jq@latest", rig_docs)
        self.assertNotIn("/home/ggcore/.config/txing/rig/aws.credentials", rig_docs)
        self.assertNotIn("/home/ggcore/.local/bin/mise exec -- txing-rig-deploy", rig_docs)
        self.assertNotIn("raw.githubusercontent.com/mparkachov/txing/main/rig/scripts/txing-rig-deploy-release", rig_docs)
        self.assertNotIn("/home/txing/.config/txing/rig/certs", rig_docs)
        self.assertIn("The package creates `ggcore`", rig_docs)
        self.assertNotIn("groupadd --system ggcore", rig_docs)
        self.assertNotIn("useradd --system --gid ggcore", rig_docs)

    def test_rig_release_deploy_runs_from_operator_assets(self) -> None:
        release_deploy = (
            REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy-release"
        ).read_text(encoding="utf-8")

        self.assertIn("gh release download", release_deploy)
        self.assertIn("txing-sparkplug-manager-linux-aarch64.tar.gz", release_deploy)
        self.assertIn("txing-ble-connectivity-linux-aarch64.tar.gz", release_deploy)
        self.assertIn("txing-aws-connectivity-linux-aarch64.tar.gz", release_deploy)
        self.assertIn("txing-rig-deploy-linux-aarch64.tar.gz", release_deploy)
        self.assertIn("TXING_RIG_COMPONENT_VERSION", release_deploy)
        self.assertIn("head -n 1", release_deploy)
        self.assertIn("are not executed locally", release_deploy)
        self.assertNotIn("sudo", release_deploy)
        self.assertNotIn("chown", release_deploy)

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
            self.assertNotIn("RequiresPrivilege", ble_recipe)
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
