from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


def _write_fake_aws(bin_dir: Path) -> None:
    aws = bin_dir / "aws"
    aws.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2 ${3:-}" in
  "configure get region")
    printf 'eu-central-1\\n'
    ;;
  "sts get-caller-identity "*)
    printf '123456789012\\n'
    ;;
  "cloudformation describe-stacks "*)
    printf 'CREATE_COMPLETE\\n'
    ;;
  "iot describe-endpoint "*)
    printf 'abc123-ats.iot.eu-central-1.amazonaws.com\\n'
    ;;
  "iot get-indexing-configuration "*)
    joined=" $* "
    if [[ "$joined" == *ThingConnectivityIndexingMode* || "$joined" == *thingConnectivityIndexingMode* ]]; then
      printf 'STATUS\\n'
    elif [[ "$joined" == *ThingIndexingMode* || "$joined" == *thingIndexingMode* ]]; then
      printf 'REGISTRY\\n'
    else
      printf '{}\\n'
    fi
    ;;
  "ssm put-parameter "*)
    printf '{}\\n'
    ;;
  *)
    printf '{}\\n'
    ;;
esac
""",
        encoding="utf-8",
    )
    aws.chmod(0o755)


def _native_aws_env(bin_dir: Path, *, stack: str | None = "town") -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    for name in (
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SELECTED_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "TXING_RIG_ID",
        "TXING_THING_ID",
    ):
        env.pop(name, None)
    if stack is None:
        env.pop("TXING_AWS_STACK", None)
        env["AWS_STACK_NAME"] = "legacy-stack"
    else:
        env["TXING_AWS_STACK"] = stack
    return env


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

    def test_project_aws_env_uses_txing_stack_and_native_cli_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            _write_fake_aws(bin_dir)
            result = subprocess.run(
                [
                    "just",
                    "--justfile",
                    str(REPO_ROOT / "justfile"),
                    "_project-aws-env",
                    "aws",
                ],
                check=True,
                env=_native_aws_env(bin_dir),
                text=True,
                stdout=subprocess.PIPE,
            )

        self.assertIn("export TXING_AWS_STACK=town", result.stdout)
        self.assertIn("export TXING_AWS_REGION=eu-central-1", result.stdout)
        self.assertNotIn("AWS_STACK_NAME", result.stdout)
        self.assertNotIn("AWS_SELECTED_PROFILE", result.stdout)
        self.assertNotIn("AWS_SHARED_CREDENTIALS_FILE", result.stdout)
        self.assertNotIn("AWS_COGNITO_DOMAIN_PREFIX", result.stdout)
        self.assertNotIn("AWS_ADMIN_EMAIL", result.stdout)
        self.assertNotIn("AWS_WEB_APP_URL", result.stdout)

    def test_project_aws_env_requires_txing_stack_without_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            _write_fake_aws(bin_dir)
            result = subprocess.run(
                [
                    "just",
                    "--justfile",
                    str(REPO_ROOT / "justfile"),
                    "_project-aws-env",
                    "aws",
                ],
                env=_native_aws_env(bin_dir, stack=None),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required TXING_AWS_STACK", result.stderr)

    def test_aws_docs_describe_native_cli_stack_inputs(self) -> None:
        aws_docs = (REPO_ROOT / "docs" / "aws.md").read_text(encoding="utf-8")
        install_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )

        self.assertTrue((REPO_ROOT / "shared" / "aws" / "deploy-init.example.json").exists())
        self.assertIn("fail unless `TXING_AWS_STACK` is", install_docs)
        self.assertIn("Txing identifiers come from environment variables", aws_docs)
        self.assertIn("native AWS CLI configuration", aws_docs)
        self.assertIn("`TXING_AWS_STACK`", aws_docs)

    def test_deploy_init_stores_web_admin_parameters_in_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()
            _write_fake_aws(bin_dir)
            parameter_file = Path(temp_dir) / "deploy-init.json"
            parameter_file.write_text(
                '{"CognitoDomainPrefix":"town","AdminEmail":"admin@example.com","WebAppUrl":"https://office.txing.dev"}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "just",
                    "--justfile",
                    str(REPO_ROOT / "justfile"),
                    "aws::deploy-init",
                    str(parameter_file),
                ],
                check=True,
                env=_native_aws_env(bin_dir, stack=None),
                text=True,
                stdout=subprocess.PIPE,
            )

        self.assertIn("/txing/stack/CognitoDomainPrefix", result.stdout)
        self.assertIn("/txing/stack/AdminEmail", result.stdout)
        self.assertIn("/txing/stack/WebAppUrl", result.stdout)

    def test_aws_check_default_does_not_require_rig_or_device_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir)
            _write_fake_aws(bin_dir)
            result = subprocess.run(
                [
                    "just",
                    "--justfile",
                    str(REPO_ROOT / "justfile"),
                    "aws::check",
                ],
                check=True,
                env=_native_aws_env(bin_dir),
                text=True,
                stdout=subprocess.PIPE,
            )

        self.assertIn("ok: CloudFormation stack town", result.stdout)
        self.assertIn("ok: AWS IoT Data-ATS endpoint", result.stdout)
        self.assertNotIn("Checking rig Python service environment", result.stdout)
        self.assertNotIn("Checking device Python service environment", result.stdout)

    def test_operator_aws_commands_use_native_cli_config(self) -> None:
        operator_files = [
            REPO_ROOT / "justfile",
            REPO_ROOT / "shared" / "aws" / "justfile",
            REPO_ROOT / "shared" / "aws" / "scripts" / "aws_lib.sh",
            REPO_ROOT / "shared" / "aws" / "scripts" / "txing-lambda-deploy-release",
            REPO_ROOT / "rig" / "justfile",
            REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy",
            REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy-release",
            REPO_ROOT / "devices" / "unit" / "justfile",
            REPO_ROOT / "devices" / "unit" / "daemon" / "justfile",
            REPO_ROOT / "devices" / "unit" / "board" / "justfile",
            REPO_ROOT / "web" / "justfile",
        ]
        for path in operator_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertNotIn("AWS_SELECTED_PROFILE", text)
                self.assertNotIn("AWS_SHARED_CREDENTIALS_FILE", text)
                self.assertNotIn("AWS_COGNITO_DOMAIN_PREFIX", text)
                self.assertNotIn("AWS_ADMIN_EMAIL", text)
                self.assertNotIn("AWS_WEB_APP_URL", text)
                self.assertNotIn("--profile", text)
                self.assertNotRegex(text, r"(?<!aws-)--region\b")

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
        self.assertIn('_project-aws-env aws)', rig_justfile)
        self.assertNotIn("TXING_RIG_ENV_FILE", rig_justfile)
        self.assertIn('scripts/txing-rig-deploy-release" "{{release}}" "{{target}}"', rig_justfile)

    def test_release_publishes_only_project_assets(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "txing-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: Txing Release", workflow)
        self.assertIn("metadata:", workflow)
        self.assertIn("build-rust-binary:", workflow)
        self.assertIn("test-rig-workspace:", workflow)
        self.assertIn("build-lambda:", workflow)
        self.assertIn("build-kvs-master:", workflow)
        self.assertIn("package-rig-deploy:", workflow)
        self.assertIn("publish:", workflow)
        self.assertIn("strategy:", workflow)
        self.assertIn("matrix:", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("actions/download-artifact@v4", workflow)
        self.assertIn("merge-multiple: true", workflow)
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
        self.assertIn("curl https://mise.run | sh", workflow)
        self.assertIn("mise/shims", workflow)
        self.assertIn("mise use --global --yes just@latest", workflow)
        self.assertIn('grep -F "libcamera.so.0.7"', workflow)
        self.assertIn('grep -F "libcamera-base.so.0.7"', workflow)
        self.assertIn('kvs_master_build_binary="devices/unit/board/kvs_master/build/$KVS_MASTER_BINARY"', workflow)
        self.assertIn('test -x "$kvs_master_build_binary"', workflow)
        self.assertIn('install -m 755 "$kvs_master_build_binary" "$RUNNER_TEMP/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("KVS_MASTER_OUTPUT_DIR", workflow)
        self.assertNotIn('-v "$RUNNER_TEMP:/out"', workflow)
        self.assertNotIn('"/out/$KVS_MASTER_BINARY"', workflow)
        self.assertNotIn("raspberrypi.gpg.key", workflow)
        self.assertNotIn("Signed-By:", workflow)
        self.assertIn("txing-sparkplug-manager-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-ble-connectivity-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-aws-connectivity-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-rig-deploy-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-witness-lambda-linux-aarch64.zip", workflow)
        self.assertIn("txing-enlist-lambda-linux-aarch64.zip", workflow)
        self.assertIn("txing-time-lambda-linux-aarch64.zip", workflow)
        self.assertIn("Install Cargo Lambda", workflow)
        self.assertIn("cargo lambda build --release", workflow)
        self.assertIn("cargo test --manifest-path rig/Cargo.toml --workspace", workflow)
        self.assertIn('release_asset_paths+=("$asset_path")', workflow)
        self.assertIn('version="$(tr -d \'[:space:]\' < VERSION)"', workflow)
        self.assertIn("git fetch --tags --force origin", workflow)
        self.assertIn("Pushed VERSION $version must be greater than latest release tag", workflow)
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
        self.assertNotIn("description: \"Version to release", workflow)
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

    def test_unit_daemon_manual_docker_build_replaces_release_channel(self) -> None:
        removed_workflow = "unit-daemon-feature-" + "prerelease.yml"
        removed_dockerfile = "Dockerfile." + "prerelease-" + "builder"
        removed_cli_flag = "--" + "prerelease"
        removed_publish_recipe = "prerelease-" + "publish"
        removed_version_suffix = "-feature" + "."
        workflow_path = REPO_ROOT / ".github" / "workflows" / removed_workflow
        daemon_dir = REPO_ROOT / "devices" / "unit" / "daemon"
        justfile = (daemon_dir / "justfile").read_text(encoding="utf-8")

        self.assertFalse(workflow_path.exists())
        self.assertTrue((daemon_dir / "Dockerfile.docker-builder").exists())
        self.assertFalse((daemon_dir / removed_dockerfile).exists())
        self.assertIn("docker-builder-image", justfile)
        self.assertIn("docker-builder-shell", justfile)
        self.assertIn("docker-build:", justfile)
        self.assertIn('docker_build_dir := daemon_dir + "/target/docker-build"', justfile)
        self.assertIn('docker_kvs_master_build_image := "debian:trixie"', justfile)
        self.assertIn('TXING_DAEMON_BUILD_VERSION="$version"', justfile)
        self.assertIn("just unit::board::build-native", justfile)
        self.assertIn("URIs: https://archive.raspberrypi.com/debian/", justfile)
        self.assertIn("apt-cache policy libcamera-dev libcamera0.7", justfile)
        self.assertIn('grep -F "libcamera.so.0.7"', justfile)
        self.assertIn('grep -F "libcamera-base.so.0.7"', justfile)
        self.assertIn('"outputs": {', justfile)
        self.assertIn("txing-unit-daemon", justfile)
        self.assertIn("txing-board-kvs-master", justfile)
        self.assertNotIn("gh release create", justfile)
        self.assertNotIn(removed_cli_flag, justfile)
        self.assertNotIn(removed_publish_recipe, justfile)
        self.assertNotIn(removed_version_suffix, justfile)

    def test_unit_daemon_root_owned_installer_removed(self) -> None:
        removed_installer = "install-" + "systemd.sh"
        removed_mise_env = "MISE_" + "PRERELEASES"
        daemon_dir = REPO_ROOT / "devices" / "unit" / "daemon"
        board_docs = (REPO_ROOT / "docs" / "components" / "board.md").read_text(
            encoding="utf-8"
        )

        self.assertFalse((daemon_dir / removed_installer).exists())
        self.assertIn('txing-unit-daemon = "github:mparkachov/txing"', board_docs)
        self.assertIn('txing-board-kvs-master = "github:mparkachov/txing"', board_docs)
        self.assertIn('asset_pattern = "txing-unit-daemon-linux-aarch64.tar.gz"', board_docs)
        self.assertIn('asset_pattern = "txing-board-kvs-master-linux-aarch64.tar.gz"', board_docs)
        self.assertIn("MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise", board_docs)
        self.assertIn(
            "Environment=TXING_KVS_MASTER_COMMAND=/root/.local/share/mise/installs/"
            "txing-board-kvs-master/latest/txing-board-kvs-master",
            board_docs,
        )
        self.assertIn(
            "ExecStart=/root/.local/share/mise/installs/"
            "txing-unit-daemon/latest/txing-unit-daemon",
            board_docs,
        )
        self.assertIn(
            "/root/.local/bin/mise upgrade txing-unit-daemon txing-board-kvs-master",
            board_docs,
        )
        self.assertIn("sudo su -", board_docs)
        self.assertNotIn(removed_installer, board_docs)
        self.assertNotIn(removed_mise_env, board_docs)
        self.assertNotIn("MISE_SHARED_INSTALL_DIRS", board_docs)
        self.assertNotIn("txing-unit-daemon-service", board_docs)
        self.assertNotIn("txing-board-kvs-master-service", board_docs)
        self.assertNotIn("mise exec -- txing-unit-daemon", board_docs)
        self.assertNotIn("mise exec -- txing-board-kvs-master", board_docs)

    def test_board_docs_use_daemon_kvs_master_release_path(self) -> None:
        removed_installer = "install-" + "systemd.sh"
        removed_mise_env = "MISE_" + "PRERELEASES"
        installation_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )
        artifacts_docs = (REPO_ROOT / "docs" / "artifacts.md").read_text(
            encoding="utf-8"
        )
        board_docs = (REPO_ROOT / "docs" / "components" / "board.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("root-owned mise release tools", installation_docs)
        self.assertIn("sudo su -", board_docs)
        self.assertIn(
            "/root/.local/share/mise/installs/txing-board-kvs-master/latest/"
            "txing-board-kvs-master",
            board_docs,
        )
        self.assertIn("just unit::daemon::role-policy <thing-id>", board_docs)
        self.assertIn("dynamic `mcp`", board_docs)
        self.assertIn("txing-board-kvs-master-linux-aarch64.tar.gz", artifacts_docs)
        self.assertIn("TXING_KVS_MASTER_COMMAND", board_docs)
        self.assertIn("daemon.env", installation_docs)
        self.assertIn("daemon.env", artifacts_docs)
        self.assertIn("Raspberry Pi OS Trixie", board_docs)
        self.assertIn("libcamera.so.0.7", board_docs)
        self.assertIn("libcamera.so.0.7", artifacts_docs)
        self.assertIn("libcamera.so.0.2", board_docs)
        self.assertIn("libcamera.so.0.4", board_docs)
        self.assertIn("run `ldd` on the installed `latest` binary", artifacts_docs)
        self.assertIn("mount /tmp ; mount /var/tmp", board_docs)
        self.assertIn(
            "/root/.local/share/mise/installs/txing-unit-daemon/latest/"
            "txing-unit-daemon",
            artifacts_docs,
        )
        self.assertIn("do not invoke mise", artifacts_docs)
        self.assertIn("depend on\ngenerated shims", artifacts_docs)
        self.assertIn("Service starts are offline", board_docs)
        self.assertIn("Release does not upgrade a board", artifacts_docs)
        self.assertNotIn("MISE_OFFLINE=1", artifacts_docs)
        self.assertNotIn("txing-unit-daemon-service", artifacts_docs)
        self.assertNotIn("txing-board-kvs-master-service", artifacts_docs)
        self.assertNotIn(removed_installer, installation_docs)
        self.assertNotIn(removed_installer, artifacts_docs)
        self.assertNotIn(removed_mise_env, artifacts_docs)
        self.assertNotIn(f"{removed_installer} | sudo bash", installation_docs)
        self.assertNotIn(f"{removed_installer} | sudo bash", artifacts_docs)
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
        deploy_script = (REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy").read_text(
            encoding="utf-8"
        )
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")
        rig_docs = (REPO_ROOT / "docs" / "components" / "rig.md").read_text(
            encoding="utf-8"
        )
        installation_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("txing-ble-connectivity", deploy_script)
        self.assertTrue((REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy-release").exists())
        self.assertNotIn("RequiresPrivilege: true", deploy_script)
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
        self.assertIn("A production rig does not need", rig_docs)
        self.assertIn("a repo checkout, mise, AWS CLI", rig_docs)
        self.assertNotIn("mise use --global aws-cli@latest gh@latest jq@latest", rig_docs)
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
        self.assertNotIn("txing-rig-deploy-linux-aarch64.tar.gz", release_deploy)
        self.assertIn("TXING_RIG_COMPONENT_VERSION", release_deploy)
        self.assertIn('TXING_RIG_DEPLOY_SCRIPT:-$script_dir/txing-rig-deploy', release_deploy)
        self.assertIn("are not executed locally", release_deploy)
        self.assertNotIn("missing rig AWS config", release_deploy)
        self.assertNotIn("sudo", release_deploy)
        self.assertNotIn("chown", release_deploy)

    def test_lambda_release_deploy_runs_from_operator_assets(self) -> None:
        aws_justfile = (REPO_ROOT / "shared" / "aws" / "justfile").read_text(
            encoding="utf-8"
        )
        aws_lib = (REPO_ROOT / "shared" / "aws" / "scripts" / "aws_lib.sh").read_text(
            encoding="utf-8"
        )
        release_deploy = (
            REPO_ROOT / "shared" / "aws" / "scripts" / "txing-lambda-deploy-release"
        ).read_text(encoding="utf-8")

        self.assertIn("deploy-lambdas release='latest'", aws_justfile)
        self.assertIn("TXING_LAMBDA_ARTIFACT_BUCKET", aws_justfile)
        self.assertIn('scripts/txing-lambda-deploy-release" "{{release}}"', aws_justfile)
        self.assertNotIn("time::lambda::build", aws_justfile)
        self.assertNotIn("witness::build", aws_justfile)
        self.assertNotIn('enlist/justfile" build', aws_justfile)
        self.assertIn("LambdaArtifactsBucketName=$artifact_bucket", aws_lib)
        self.assertIn("gh release download", release_deploy)
        self.assertIn("txing-witness-lambda-linux-aarch64.zip", release_deploy)
        self.assertIn("txing-enlist-lambda-linux-aarch64.zip", release_deploy)
        self.assertIn("txing-time-lambda-linux-aarch64.zip", release_deploy)
        self.assertIn('version_key="lambda/$function_name/$version/bootstrap.zip"', release_deploy)
        self.assertIn('current_key="lambda/$function_name/current/bootstrap.zip"', release_deploy)
        self.assertIn("aws lambda update-function-code", release_deploy)
        self.assertIn("does not exist yet; seeded S3 bootstrap", release_deploy)
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
                }
            )
            for removed_name in (
                "AWS_REGION",
                "AWS_DEFAULT_REGION",
                "AWS_SELECTED_PROFILE",
                "AWS_SHARED_CREDENTIALS_FILE",
                "TXING_RIG_ENV_FILE",
            ):
                env.pop(removed_name, None)
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

    def test_rig_deploy_requires_txing_stack_for_real_runs(self) -> None:
        script = REPO_ROOT / "rig" / "scripts" / "txing-rig-deploy"
        env = os.environ.copy()
        for removed_name in (
            "TXING_AWS_STACK",
            "AWS_STACK_NAME",
            "TXING_RIG_ENV_FILE",
            "AWS_SELECTED_PROFILE",
            "AWS_SHARED_CREDENTIALS_FILE",
        ):
            env.pop(removed_name, None)
        env["TXING_RIG_DEPLOY_DRY_RUN"] = "false"

        result = subprocess.run(
            [str(script), "raspi"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TXING_AWS_STACK is required", result.stderr)
        self.assertNotIn("missing rig AWS config", result.stderr)

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
                }
            )
            for removed_name in (
                "AWS_REGION",
                "AWS_DEFAULT_REGION",
                "AWS_SELECTED_PROFILE",
                "AWS_SHARED_CREDENTIALS_FILE",
                "TXING_RIG_ENV_FILE",
            ):
                env.pop(removed_name, None)
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
