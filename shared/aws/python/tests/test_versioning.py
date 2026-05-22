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
        """#!/bin/sh
set -eu
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
    case "$joined" in
      *ThingConnectivityIndexingMode*|*thingConnectivityIndexingMode*)
      printf 'STATUS\\n'
      ;;
      *ThingIndexingMode*|*thingIndexingMode*)
      printf 'REGISTRY\\n'
      ;;
      *)
      printf '{}\\n'
      ;;
    esac
    ;;
  "ssm put-parameter "*)
    printf '{}\\n'
    ;;
  "ssm delete-parameter "*)
    printf '{}\\n'
    ;;
  "ssm get-parameter "*)
    joined=" $* "
    case "$joined" in
      *"/txing/stack/ReleasePublisherFunctionName"*|*"ReleasePublisherFunctionName"*)
        printf 'town-aws-publish-release\\n'
        ;;
      *"/txing/stack/EnlistFunctionName"*|*"EnlistFunctionName"*)
        printf 'town-aws-enlist-txing\\n'
        ;;
      *"/txing/stack/WitnessFunctionName"*|*"WitnessFunctionName"*)
        printf 'town-witness\\n'
        ;;
      *"/txing/stack/CloudRigRuntimeFunctionName"*|*"CloudRigRuntimeFunctionName"*)
        printf 'town-cloud-rig\\n'
        ;;
      *"/txing/stack/CloudMcuRuntimeFunctionName"*|*"CloudMcuRuntimeFunctionName"*)
        printf 'town-cloud-mcu\\n'
        ;;
      *)
        printf 'txing-parameter-value\\n'
        ;;
    esac
    ;;
  "ssm get-parameters-by-path "*)
    printf '[]\\n'
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
            self.assertIn("export TXING_VERSION='1.2.3'", clean)
            self.assertIn("export TXING_GIT_DIRTY='false'", clean)

            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(
                ["just", "--justfile", str(repo / "justfile"), "_project-version-env"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertIn("export TXING_VERSION='1.2.3'", dirty)
            self.assertIn("export TXING_GIT_DIRTY='true'", dirty)
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

        self.assertIn("export TXING_AWS_STACK='town'", result.stdout)
        self.assertIn("export TXING_AWS_BASE_STACK='town-aws-base'", result.stdout)
        self.assertIn("export TXING_AWS_REGION='eu-central-1'", result.stdout)
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

    def test_delete_init_removes_web_admin_parameters_from_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()
            _write_fake_aws(bin_dir)
            result = subprocess.run(
                [
                    "just",
                    "--justfile",
                    str(REPO_ROOT / "justfile"),
                    "aws::delete-init",
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

        self.assertIn("ok: CloudFormation stack town-aws-base", result.stdout)
        self.assertIn("ok: AWS IoT Data-ATS endpoint", result.stdout)
        self.assertNotIn("Checking rig Python service environment", result.stdout)
        self.assertNotIn("Checking device Python service environment", result.stdout)

    def test_operator_aws_commands_use_native_cli_config(self) -> None:
        operator_files = [
            REPO_ROOT / "justfile",
            REPO_ROOT / "shared" / "aws" / "justfile",
            REPO_ROOT / "shared" / "aws" / "scripts" / "aws_lib.sh",
            REPO_ROOT / "rig" / "justfile",
            REPO_ROOT / "devices" / "unit" / "justfile",
            REPO_ROOT / "devices" / "unit" / "daemon" / "justfile",
            REPO_ROOT / "office" / "justfile",
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

    def test_rig_daemon_justfile_supports_local_control_and_cert(self) -> None:
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")
        aws_justfile = (REPO_ROOT / "shared" / "aws" / "justfile").read_text(
            encoding="utf-8"
        )
        aws_lib = (
            REPO_ROOT / "shared" / "aws" / "scripts" / "aws_lib.sh"
        ).read_text(encoding="utf-8")
        env_template = (REPO_ROOT / "rig" / "rig-daemon.env.template").read_text(
            encoding="utf-8"
        )

        self.assertIn("start config_dir=config_dir no_ble='false':", rig_justfile)
        self.assertIn("stop:", rig_justfile)
        self.assertIn("restart config_dir=config_dir no_ble='false':", rig_justfile)
        self.assertIn("txing-sparkplug-manager.pid", rig_justfile)
        self.assertIn("txing-ble-connectivity.pid", rig_justfile)
        self.assertIn("TXING_RIG_IPC_SOCKET", rig_justfile)
        self.assertIn("install-mise-tools:", rig_justfile)
        self.assertNotIn("TXING_RIG_ENV_FILE", rig_justfile)
        self.assertNotIn("deploy target='auto'", rig_justfile)
        self.assertNotIn("check-greengrass-lite", rig_justfile)
        self.assertNotIn("greengrass", rig_justfile.lower())
        self.assertIn("cert thing_id='':", aws_justfile)
        self.assertIn("txing_generate_iot_certificate_bundle", aws_justfile)
        self.assertIn("RigRuntimeManagedPolicyArn", aws_lib)
        self.assertIn("txing-rig-daemon-$thing_id", aws_lib)
        self.assertIn("rig-daemon.env.template", aws_justfile)
        self.assertNotIn("publish-rig release='latest'", aws_justfile)
        self.assertNotIn("python -m aws_admin.publish_release rig --release", aws_justfile)
        self.assertIn("TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock", env_template)
        self.assertIn("TXING_BLE_NO_BLE=false", env_template)

    def test_release_publishes_only_project_assets(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "txing-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("name: Txing Release", workflow)
        self.assertIn("metadata:", workflow)
        self.assertIn("build-rust-binary:", workflow)
        self.assertIn("build-go-rig-binary:", workflow)
        self.assertIn("build-lambda:", workflow)
        self.assertIn("build-kvs-master:", workflow)
        self.assertNotIn("package-rig-deploy:", workflow)
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
        self.assertIn("just unit::daemon::kvs-submodules", workflow)
        self.assertIn("just unit::daemon::kvs-build-native", workflow)
        self.assertNotIn("just unit::board::", workflow)
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
        self.assertNotIn("txing-aws-connectivity-linux-aarch64.tar.gz", workflow)
        self.assertNotIn("txing-rig-deploy-linux-aarch64.tar.gz", workflow)
        self.assertIn("txing-witness-lambda-linux-aarch64.zip", workflow)
        self.assertNotIn("txing-enlist-lambda-linux-aarch64.zip", workflow)
        self.assertIn("txing-cloud-rig-lambda-linux-aarch64.zip", workflow)
        self.assertIn("txing-cloud-mcu-lambda-linux-aarch64.zip", workflow)
        self.assertIn("for version in 1.26 1.25 1.24", workflow)
        self.assertIn('candidate="golang-${version}-go"', workflow)
        self.assertIn('echo "$go_root/bin" >>"$GITHUB_PATH"', workflow)
        self.assertIn("Restore Go cache", workflow)
        self.assertIn("~/go/pkg/mod", workflow)
        self.assertIn("~/.cache/go-build", workflow)
        self.assertIn("package_path: ./cmd/txing-witness-lambda", workflow)
        self.assertNotIn("package_path: ./cmd/txing-enlist-lambda", workflow)
        self.assertIn("package_path: ./cmd/txing-cloud-rig-lambda", workflow)
        self.assertIn("package_path: ./cmd/txing-cloud-mcu-lambda", workflow)
        self.assertIn("GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go test -tags lambda.norpc ./...", workflow)
        self.assertIn("GOOS=linux GOARCH=arm64 CGO_ENABLED=1 go test ./...", workflow)
        self.assertIn("package_path: ./cmd/txing-sparkplug-manager", workflow)
        self.assertIn("package_path: ./cmd/txing-ble-connectivity", workflow)
        self.assertIn("go build -trimpath -tags lambda.norpc -ldflags=\"-s -w\"", workflow)
        self.assertIn("-o \"$RUNNER_TEMP/${{ matrix.function_name }}\"", workflow)
        self.assertIn('source="$RUNNER_TEMP/${{ matrix.function_name }}"', workflow)
        self.assertIn('install -m 755 "$source" "$package_dir/bootstrap"', workflow)
        self.assertIn("ELF 64-bit LSB executable, ARM aarch64", workflow)
        self.assertIn("statically linked", workflow)
        self.assertIn('zip -q "$asset_path" bootstrap', workflow)
        self.assertIn('archive_listing="$(unzip -Z1 "$asset_path")"', workflow)
        self.assertNotIn("Test and build ${{ matrix.function_name }} in Amazon Linux 2023", workflow)
        self.assertNotIn("public.ecr.aws/amazonlinux/amazonlinux:2023", workflow)
        self.assertNotIn("Lambda bootstrap requires glibc newer than AL2023 supports", workflow)
        self.assertNotIn("target/release/${{ matrix.function_name }}", workflow)
        self.assertNotIn("lock_file:", workflow)
        self.assertNotIn("Install Cargo Lambda", workflow)
        self.assertNotIn("cargo lambda", workflow)
        self.assertNotIn("cargo-lambda", workflow)
        self.assertNotIn("zig", workflow.lower())
        self.assertNotIn("cargo test --manifest-path rig/Cargo.toml --workspace", workflow)
        self.assertIn('release_asset_paths+=("$asset_path")', workflow)
        self.assertIn('version="$(tr -d \'[:space:]\' < VERSION)"', workflow)
        self.assertIn("git fetch --tags --force origin", workflow)
        self.assertIn("Pushed VERSION $version must be greater than latest release tag", workflow)
        self.assertIn('release_target="$(git rev-parse HEAD)"', workflow)
        self.assertNotIn("Release workflow is only allowed from main", workflow)
        self.assertIn("python3 release/src/txing_release/cli.py check", workflow)
        self.assertIn('RELEASE_RETENTION_COUNT: "10"', workflow)
        self.assertIn("Prune old project releases", workflow)
        self.assertIn("--json tagName,publishedAt,createdAt", workflow)
        self.assertIn("project_release_pattern = re.compile", workflow)
        self.assertIn("gh release delete", workflow)
        self.assertIn("--cleanup-tag", workflow)
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
        self.assertFalse((REPO_ROOT / "witness" / "CargoLambda.toml").exists())
        self.assertFalse((REPO_ROOT / "shared" / "aws" / "enlist" / "CargoLambda.toml").exists())
        self.assertFalse((REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "CargoLambda.toml").exists())

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
        self.assertIn("just unit::daemon::kvs-submodules", justfile)
        self.assertIn("just unit::daemon::kvs-build-native", justfile)
        self.assertNotIn("just unit::board::", justfile)
        self.assertIn("URIs: https://archive.raspberrypi.com/debian/", justfile)
        self.assertIn("apt-cache policy libcamera-dev libcamera0.7", justfile)
        self.assertIn('grep -F "libcamera.so.0.7"', justfile)
        self.assertIn('grep -F "libcamera-base.so.0.7"', justfile)
        self.assertIn("outputs: {", justfile)
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
        self.assertIn("keeps the newest 10 project", artifacts_docs)
        self.assertIn("prunes older project releases down to", artifacts_docs)
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
        self.assertNotIn('txing-aws-connectivity = "github:$owner/$repo"', installer)
        self.assertNotIn('txing-rig-deploy = "github:$owner/$repo"', installer)
        self.assertIn('[settings]', installer)
        self.assertIn('fetch_remote_versions_cache = "0s"', installer)
        self.assertIn('asset_pattern = "txing-sparkplug-manager-linux-aarch64.tar.gz"', installer)
        self.assertIn('asset_pattern = "txing-ble-connectivity-linux-aarch64.tar.gz"', installer)
        self.assertNotIn('asset_pattern = "txing-rig-deploy-linux-aarch64.tar.gz"', installer)
        self.assertNotIn("txing-greengrass-lite", installer)
        self.assertNotIn("aws-greengrass-lite-deb-arm64.zip", installer)
        self.assertNotIn('version_prefix = "greengrass-lite-v"', installer)
        self.assertNotIn("prerelease = true", installer)
        self.assertNotIn("sudo", installer)
        self.assertNotIn("run as root", installer)
        self.assertNotIn("chown", installer)

    def test_rig_docs_describe_standalone_daemons(self) -> None:
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")
        rig_docs = (REPO_ROOT / "docs" / "components" / "rig.md").read_text(
            encoding="utf-8"
        )
        installation_docs = (REPO_ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("RequiresPrivilege: true", rig_justfile)
        self.assertIn("Canonical `raspi` rig installation", installation_docs)
        self.assertIn("components/rig.md", installation_docs)
        self.assertIn("txing-sparkplug-manager", rig_docs)
        self.assertIn("txing-ble-connectivity", rig_docs)
        self.assertIn("rig-daemon.target", rig_docs)
        self.assertIn("/root/.config/txing/rig-daemon", rig_docs)
        self.assertIn("/run/txing-rig/rig-ipc.sock", rig_docs)
        self.assertIn("PartOf=rig-daemon.target", rig_docs)
        self.assertIn("sudo systemctl restart rig-daemon.target", rig_docs)
        self.assertIn("mise upgrade", rig_docs)
        self.assertIn("bluetooth", rig_docs)
        self.assertNotIn("aws-greengrass-lite-deb-arm64.zip", rig_docs)
        self.assertNotIn("/etc/greengrass", rig_docs)
        self.assertNotIn("/var/lib/greengrass", rig_docs)
        self.assertNotIn("just aws::publish-rig latest", rig_docs)
        self.assertNotIn("gg_component", rig_docs)
        self.assertIn("root-owned `mise`", rig_docs)

    def test_lambda_release_publish_uses_shared_python_only(self) -> None:
        aws_justfile = (REPO_ROOT / "shared" / "aws" / "justfile").read_text(
            encoding="utf-8"
        )
        aws_lib = (REPO_ROOT / "shared" / "aws" / "scripts" / "aws_lib.sh").read_text(
            encoding="utf-8"
        )
        scripts_dir = REPO_ROOT / "shared" / "aws" / "scripts"

        self.assertIn("publish release='latest'", aws_justfile)
        self.assertIn("publish-lambda release='latest'", aws_justfile)
        self.assertNotIn("publish-rig release='latest'", aws_justfile)
        self.assertNotIn("deploy-lambdas release='latest'", aws_justfile)
        self.assertNotIn("deploy-lambdas stack_name=stack_name", aws_justfile)
        self.assertNotIn("deploy-local-lambda", aws_justfile)
        self.assertIn("TXING_LAMBDA_ARTIFACT_BUCKET", aws_justfile)
        self.assertIn("TXING_LAMBDA_FUNCTIONS_JSON", aws_justfile)
        self.assertIn("python -m aws_admin.publish_release lambda --release", aws_justfile)
        self.assertIn("stack_parameter ReleasePublisherFunctionName", aws_justfile)
        self.assertIn("deploy-base stack_name=stack_name", aws_justfile)
        self.assertIn("clean-stack::deploy", aws_justfile)
        self.assertIn("witness::deploy", aws_justfile)
        self.assertIn("cloud-mcu::deploy", aws_justfile)
        self.assertNotIn("scripts/txing-lambda-deploy", aws_justfile)
        self.assertNotIn("witness::build", aws_justfile)
        self.assertNotIn('enlist/justfile" build', aws_justfile)
        self.assertIn("LambdaArtifactsBucketName=$artifact_bucket", aws_lib)
        self.assertIn("AwsAdminCodeS3Bucket=$artifact_bucket", aws_lib)
        self.assertIn("AwsAdminCodeS3Key=$admin_key", aws_lib)
        self.assertIn("cfn/aws-admin/$admin_hash.zip", aws_lib)
        self.assertFalse((scripts_dir / "txing-lambda-deploy-release").exists())
        self.assertFalse((scripts_dir / "txing-lambda-deploy-local").exists())

    def test_greengrass_lite_submodule_removed_for_distribution_install(self) -> None:
        self.assertFalse((REPO_ROOT / "rig" / "greengrass-lite-build.env").exists())
        self.assertFalse(
            (REPO_ROOT / "rig" / "scripts" / "greengrass-lite-version").exists()
        )

        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertNotIn(
            '[submodule "aws-greengrass/aws-greengrass-lite"]', gitmodules
        )
        self.assertNotIn(
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

    def test_greengrass_lite_helper_removed(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "rig" / "scripts" / "txing-greengrass-lite").exists()
        )

    def test_release_version_is_manual(self) -> None:
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "release-version.yml").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "release_version.py").exists())


if __name__ == "__main__":
    unittest.main()
