from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


def _template_text() -> str:
    return (AWS_DIR / "template.yaml").read_text(encoding="utf-8")


def _witness_template_text() -> str:
    return (REPO_ROOT / "witness" / "template.yaml").read_text(encoding="utf-8")


def _cloud_rig_template_text() -> str:
    return (
        REPO_ROOT
        / "devices"
        / "cloud-mcu"
        / "lambda"
        / "cmd"
        / "txing-cloud-rig-lambda"
        / "template.yaml"
    ).read_text(encoding="utf-8")


def _cloud_mcu_lambda_template_text() -> str:
    return (
        REPO_ROOT
        / "devices"
        / "cloud-mcu"
        / "lambda"
        / "cmd"
        / "txing-cloud-mcu-lambda"
        / "template.yaml"
    ).read_text(encoding="utf-8")


def _aws_lambda_template_text(name: str) -> str:
    return (
        AWS_DIR / "lambdas" / name / "template.yaml"
    ).read_text(encoding="utf-8")


def _parse_env_template_exports(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


class AwsTemplatePolicyTests(unittest.TestCase):
    def test_device_daemon_policy_scopes_mavlink_master_access_to_capability(self) -> None:
        script = AWS_DIR / "scripts" / "aws_lib.sh"

        def render(thing_id: str, capabilities: str) -> dict[str, object]:
            with tempfile.TemporaryDirectory() as tempdir:
                policy_path = Path(tempdir) / "policy.json"
                subprocess.run(
                    [
                        "sh",
                        "-c",
                        'set -eu; . "$1"; TXING_AWS_REGION=eu-central-1; export TXING_AWS_REGION; '
                        'txing_cert_write_device_daemon_policy "$2" aws 123456789012 "$3" '
                        'txing/town/rig/tbot-local "$4"',
                        "sh",
                        str(script),
                        str(policy_path),
                        thing_id,
                        capabilities,
                    ],
                    check=True,
                )
                return json.loads(policy_path.read_text(encoding="utf-8"))

        tbot_policy = render("tbot-local", "board,mavlink,video")
        cyberbrick_policy = render("cyberbrick-local", "board,mavlink,video")
        unit_policy = render("unit-local", "board,mcp,video")

        def master_resources(policy: dict[str, object]) -> list[str]:
            statements = policy["Statement"]
            self.assertIsInstance(statements, list)
            statement = next(
                item for item in statements if item["Sid"] == "DaemonKvsMaster"
            )
            resources = statement["Resource"]
            self.assertIsInstance(resources, list)
            return resources

        self.assertEqual(
            master_resources(tbot_policy),
            [
                "arn:aws:kinesisvideo:eu-central-1:123456789012:channel/tbot-local-board-video/*",
                "arn:aws:kinesisvideo:eu-central-1:123456789012:channel/tbot-local-mavlink/*",
            ],
        )
        self.assertEqual(
            master_resources(unit_policy),
            ["arn:aws:kinesisvideo:eu-central-1:123456789012:channel/unit-local-board-video/*"],
        )
        self.assertEqual(
            master_resources(cyberbrick_policy),
            [
                "arn:aws:kinesisvideo:eu-central-1:123456789012:channel/cyberbrick-local-board-video/*",
                "arn:aws:kinesisvideo:eu-central-1:123456789012:channel/cyberbrick-local-mavlink/*",
            ],
        )

    def test_rig_and_device_video_topics_are_authorized(self) -> None:
        template = _template_text()

        self.assertIn("Sid: RigVideoDiscoveryTopics", template)
        self.assertIn("Sid: RigVideoDiscoveryTopicFilters", template)
        self.assertIn("topic/txings/*/video/descriptor", template)
        self.assertIn("topic/txings/*/video/status", template)
        self.assertIn("topicfilter/txings/*/video/descriptor", template)
        self.assertIn("topicfilter/txings/*/video/status", template)
        self.assertIn("Sid: DeviceVideoTopics", template)
        self.assertIn("iot:RetainPublish", template)

    def test_rig_capability_service_topics_are_authorized(self) -> None:
        template = _template_text()

        self.assertIn("Sid: RigCapabilityServiceTopics", template)
        self.assertIn("Sid: RigCapabilityServiceTopicFilters", template)
        self.assertIn("topic/txings/*/capability/v2/command", template)
        self.assertIn("topic/txings/*/capability/v2/state", template)
        self.assertIn("topic/txings/*/capability/v2/command-result", template)
        self.assertIn("topicfilter/txings/*/capability/v2/state", template)
        self.assertIn("topicfilter/txings/*/capability/v2/command-result", template)

    def test_device_capability_service_topics_are_authorized(self) -> None:
        template = _template_text()

        self.assertIn("Sid: DeviceCapabilityServiceTopics", template)
        self.assertIn("topic/txings/*/capability/v2/state", template)

    def test_device_mqtt_mcp_topics_are_authorized_for_operator_sessions(self) -> None:
        template = _template_text()

        self.assertIn("Sid: DeviceMcpTopics", template)
        self.assertIn("Sid: DeviceMcpTopicFilters", template)
        self.assertIn("topic/txings/*/mcp/descriptor", template)
        self.assertIn("topic/txings/*/mcp/status", template)
        self.assertIn("topic/txings/*/mcp/session/*/c2s", template)
        self.assertIn("topic/txings/*/mcp/session/*/s2c", template)
        self.assertIn("topicfilter/txings/*/mcp/descriptor", template)
        self.assertIn("topicfilter/txings/*/mcp/status", template)
        self.assertIn("topicfilter/txings/*/mcp/session/*/s2c", template)

    def test_legacy_raw_cmd_vel_topic_permissions_are_removed(self) -> None:
        template = _template_text()

        self.assertNotIn("Sid: RigCmdVelTopics", template)
        self.assertNotIn("Sid: RigCmdVelTopicFilters", template)
        self.assertNotIn("Sid: DeviceCmdVelTopics", template)
        self.assertNotIn("Sid: DeviceCmdVelTopicFilters", template)
        self.assertNotIn("board/cmd_vel", template)

    def test_base_template_embeds_sparkplug_witness_projection(self) -> None:
        root_template = _template_text()
        template = _witness_template_text()

        self.assertIn("WitnessFunction", template)
        self.assertIn("WitnessTopicRule", template)
        self.assertIn("WitnessInvokePermission", template)
        self.assertIn("WitnessLogGroup", template)
        self.assertIn(
            "LogGroupName: !Sub /aws/lambda/${EnvironmentStackName}-witness",
            template,
        )
        self.assertIn("RetentionInDays: 14", template)
        self.assertIn("sparkplug-witness", template)
        self.assertIn("Sid: WitnessShadowUpdate", template)
        self.assertIn("- iot:GetThingShadow", template)
        self.assertIn("- iot:UpdateThingShadow", template)
        self.assertIn("Sid: WitnessDescribeThings", template)
        self.assertIn("Action: iot:DescribeThing", template)
        self.assertIn("Runtime: provided.al2023", template)
        self.assertIn("Handler: bootstrap", template)
        self.assertIn("Architectures:", template)
        self.assertIn("- arm64", template)
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-witness", template
        )
        self.assertIn("MemorySize: 128", template)
        self.assertIn("LambdaArtifactsBucketName:", template)
        self.assertIn("S3Bucket: !Ref LambdaArtifactsBucketName", template)
        self.assertIn("S3Key: lambda/txing-witness-lambda/current/bootstrap.zip", template)
        self.assertNotIn("witness/target/lambda/txing-witness-lambda/bootstrap.zip", template)
        self.assertIn("encode(*, 'base64')", template)
        self.assertIn("iot:DescribeEndpoint", template)
        self.assertNotIn("WitnessFunctionName:", root_template)
        self.assertNotIn("WitnessFunctionArn:", root_template)
        self.assertIn("WitnessFunctionName:", template)

    def test_template_uses_dynamic_txing_log_group_prefix_for_rig_logs(self) -> None:
        template = _template_text()

        self.assertNotIn("LogGroupName: /town/rig/txing", template)
        self.assertIn("logs:CreateLogGroup", template)
        self.assertIn("logs:PutRetentionPolicy", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn(
            "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:txing/*",
            template,
        )
        self.assertIn("Value: txing/<town-thing-name>/<rig-thing-name>", template)
        self.assertIn(
            "Value: txing/<town-thing-name>/<rig-thing-name>/<device-thing-name>",
            template,
        )

    def test_template_grants_direct_shadow_read_in_both_web_permission_layers(self) -> None:
        template = _template_text()

        self.assertIn("TxingWebAdminIotPolicy", template)
        self.assertIn("WebIotPolicyName:", template)
        self.assertIn(
            "Resource: !Sub arn:${AWS::Partition}:iot:${AWS::Region}:${AWS::AccountId}:thing/*",
            template,
        )
        self.assertIn(
            "Sid: AllowDirectThingShadowReads",
            template,
        )
        self.assertIn(
            "PolicyName: iot-shadow-direct-access-txing",
            template,
        )

    def test_device_runtime_policy_allows_describe_thing(self) -> None:
        template = _template_text()

        self.assertIn("Sid: DeviceDescribeThing", template)
        self.assertIn("Action: iot:DescribeThing", template)

    def test_device_runtime_policy_allows_sparkplug_command_subscribe(self) -> None:
        template = _template_text()

        self.assertIn("Sid: DeviceSparkplugMqttTopics", template)
        self.assertIn("Sid: DeviceSparkplugMqttTopicFilters", template)
        self.assertIn("topic/spBv1.0/*", template)
        self.assertIn("topicfilter/spBv1.0/*", template)

    def test_template_defines_unit_daemon_certificate_resources(self) -> None:
        template = _template_text()

        self.assertIn("TxingDaemonIotPolicy:", template)
        self.assertIn("Sid: DaemonConnect", template)
        self.assertIn("client/${!iot:Connection.Thing.ThingName}-daemon-*", template)
        self.assertIn("iot:Connection.Thing.IsAttached", template)
        self.assertIn("Sid: DaemonOwnThingTopics", template)
        self.assertIn(
            "topic/$aws/things/${!iot:Connection.Thing.ThingName}/shadow/name/*/update",
            template,
        )
        self.assertIn("Sid: DaemonOwnThingTopicFilters", template)
        self.assertIn(
            "topic/txings/${!iot:Connection.Thing.ThingName}/*",
            template,
        )
        self.assertIn(
            "topicfilter/txings/${!iot:Connection.Thing.ThingName}/*",
            template,
        )
        self.assertIn("Sid: DaemonCredentialProvider", template)
        self.assertIn(
            "rolealias/txing-daemon-${!iot:Connection.Thing.ThingName}",
            template,
        )
        self.assertIn("DeviceDaemonIotPolicyName:", template)
        self.assertNotIn("Sid: DaemonBoardShadowUpdate", template)
        self.assertNotIn("Sid: DaemonMcpShadowUpdate", template)
        self.assertNotIn("Sid: DaemonVideoShadowUpdate", template)
        self.assertNotIn("Sid: DaemonMcpRetainedTopics", template)
        self.assertNotIn("Sid: DaemonVideoRetainedTopics", template)
        self.assertNotIn("Sid: DaemonMcpSessionReceive", template)
        self.assertNotIn("Sid: DaemonMcpSessionTopics", template)
        self.assertNotIn("Sid: DaemonCapabilityState", template)
        self.assertNotIn("Sid: DaemonSparkplugShadowRead", template)
        self.assertNotIn("TxingDaemonCredentialRole:", template)
        self.assertNotIn("DeviceDaemonCredentialRoleAlias:", template)

    def test_aws_cert_recipe_uses_one_shared_device_daemon_template(self) -> None:
        aws_justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")
        daemon_env_template = (
            REPO_ROOT / "devices" / "common" / "daemon.env.template"
        ).read_text(encoding="utf-8")
        daemon_justfile = (
            REPO_ROOT / "devices" / "common" / "board" / "justfile"
        ).read_text(encoding="utf-8")
        root_gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("cert thing_id='':", aws_justfile)
        self.assertIn("device_daemon_env_template", aws_justfile)
        self.assertIn('devices_dir := project_root + "/devices"', aws_justfile)
        self.assertNotIn("mac_daemon_env_template", aws_justfile)
        self.assertIn("txing_generate_iot_certificate_bundle", aws_justfile)
        self.assertIn("DeviceDaemonIotPolicyName", aws_lib)
        self.assertIn("deviceType:unit", aws_lib)
        self.assertIn('daemon_role_name="txing-daemon-$thing_id"', aws_lib)
        self.assertIn('iot_role_alias="txing-daemon-$thing_id"', aws_lib)
        self.assertIn("credentials.iot.amazonaws.com", aws_lib)
        self.assertIn("DaemonSparkplugShadowRead", aws_lib)
        self.assertIn("arn:${partition}:iot:${TXING_AWS_REGION}:${account_id}:thing/${thing_id}/sparkplug", aws_lib)
        self.assertIn('cloudwatch_log_group="txing/${town_id}/${rig_id}/${thing_id}"', aws_lib)
        self.assertIn("DaemonCloudWatchLogsWrite", aws_lib)
        self.assertIn("logs:CreateLogGroup", aws_lib)
        self.assertIn("logs:CreateLogStream", aws_lib)
        self.assertIn("logs:DescribeLogStreams", aws_lib)
        self.assertIn("DaemonKvsMaster", aws_lib)
        self.assertIn("kinesisvideo:ConnectAsMaster", aws_lib)
        self.assertIn("arn:${partition}:kinesisvideo:${TXING_AWS_REGION}:${account_id}:channel/${thing_id}-board-video/*", aws_lib)
        self.assertIn('role-policy device thing_id=', daemon_justfile)
        self.assertIn("logs:PutRetentionPolicy", aws_lib)
        self.assertIn("logs:PutLogEvents", aws_lib)
        self.assertIn("arn:${partition}:logs:${TXING_AWS_REGION}:${account_id}:log-group:${cloudwatch_log_group}", aws_lib)
        self.assertIn("arn:${partition}:logs:${TXING_AWS_REGION}:${account_id}:log-group:${cloudwatch_log_group}:log-stream:*", aws_lib)
        self.assertIn("create-role-alias", aws_lib)
        self.assertIn("put-role-policy", aws_lib)
        self.assertIn("create-keys-and-certificate", aws_lib)
        self.assertIn('txing_cert_create_iot_bundle "$thing_id" "$output_dir" "$daemon_policy_name"', aws_lib)
        self.assertIn('attach-policy --policy-name "$policy_name"', aws_lib)
        self.assertIn("attach-thing-principal", aws_lib)
        self.assertIn("--thing-principal-type EXCLUSIVE_THING", aws_lib)
        self.assertIn('printf \'%s/certs/%s\\n\' "$TXING_PROJECT_ROOT" "$thing_id"', aws_lib)
        self.assertIn('${thing_id}-daemon-config.tgz', aws_lib)
        self.assertIn('COPYFILE_DISABLE=1 tar -C "$output_dir" -czf "$tarball_path"', aws_lib)
        self.assertIn('txing_cert_stage_board_services "$output_dir" "$devices_dir"', aws_lib)
        self.assertIn('txing_cert_write_runtime_tarball "$output_dir" "$tarball_path" services', aws_lib)
        self.assertIn("configTarball", aws_lib)
        self.assertIn("/certs/", root_gitignore)
        self.assertIn('env_file="$output_dir/daemon.env"', aws_lib)
        self.assertIn('"$env_template" >"$env_file"', aws_lib)
        self.assertIn('cert_path="$output_dir/certificate.pem.crt"', aws_lib)
        self.assertIn(
            'video_channel_name="${TXING_BOARD_VIDEO_CHANNEL_NAME:-${thing_id}-board-video}"',
            aws_lib,
        )
        self.assertIn("TXING_BOARD_VIDEO_CHANNEL_NAME={{TXING_BOARD_VIDEO_CHANNEL_NAME}}", daemon_env_template)
        self.assertIn("TXING_DAEMON_CAPABILITIES={{TXING_DAEMON_CAPABILITIES}}", daemon_env_template)
        self.assertIn('daemon_capabilities="$(txing_cert_device_daemon_capabilities', aws_lib)
        # Local socket paths must stay out of the identity bundle so each
        # binary's compiled device-correct default applies; setting them here
        # breaks any board running another device type's binaries.
        self.assertNotIn("TXING_HARDWARE_WORKER_SOCKET_PATH=", daemon_env_template)
        self.assertNotIn(
            "TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH=", daemon_env_template
        )
        self.assertIn("TXING_HARDWARE_WORKER_TIMEOUT_MS=700", daemon_env_template)
        self.assertIn("AWS_REGION={{AWS_REGION}}", daemon_env_template)
        self.assertNotIn("export TXING_", daemon_env_template)
        self.assertNotIn("export AWS_REGION", daemon_env_template)
        self.assertNotIn("AWS_DEFAULT_REGION", daemon_env_template)
        self.assertNotIn("TXING_BOARD_VIDEO_REGION", daemon_env_template)
        daemon_env_values = _parse_env_template_exports(daemon_env_template)
        for key in (
            "TXING_MOTOR_ENABLED",
            "TXING_MOTOR_PWM_SYSFS_ROOT",
            "TXING_MOTOR_RAW_MAX_SPEED",
            "TXING_MOTOR_CMD_RAW_MIN_SPEED",
            "TXING_MOTOR_CMD_RAW_MAX_SPEED",
            "TXING_MOTOR_PWM_HZ",
            "TXING_MOTOR_PWM_CHIP",
            "TXING_MOTOR_LEFT_PWM_CHANNEL",
            "TXING_MOTOR_RIGHT_PWM_CHANNEL",
            "TXING_MOTOR_GPIO_CHIP",
            "TXING_MOTOR_LEFT_DIR_GPIO",
            "TXING_MOTOR_RIGHT_DIR_GPIO",
            "TXING_MOTOR_LEFT_INVERTED",
            "TXING_MOTOR_RIGHT_INVERTED",
            "TXING_MOTOR_TRACK_WIDTH_M",
            "TXING_MOTOR_MAX_WHEEL_LINEAR_SPEED_MPS",
            "TXING_MOTOR_LEFT_TRACK_POWER_PERCENT",
            "TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT",
            "TXING_MOTOR_WATCHDOG_TIMEOUT_MS",
        ):
            self.assertIn(key, daemon_env_values)

        self.assertIn(daemon_env_values["TXING_MOTOR_ENABLED"], {"true", "false"})
        self.assertIn(daemon_env_values["TXING_MOTOR_LEFT_INVERTED"], {"true", "false"})
        self.assertIn(daemon_env_values["TXING_MOTOR_RIGHT_INVERTED"], {"true", "false"})
        self.assertTrue(daemon_env_values["TXING_MOTOR_PWM_SYSFS_ROOT"].startswith("/"))

        raw_max_speed = int(daemon_env_values["TXING_MOTOR_RAW_MAX_SPEED"])
        cmd_raw_min_speed = int(daemon_env_values["TXING_MOTOR_CMD_RAW_MIN_SPEED"])
        cmd_raw_max_speed = int(daemon_env_values["TXING_MOTOR_CMD_RAW_MAX_SPEED"])
        pwm_hz = int(daemon_env_values["TXING_MOTOR_PWM_HZ"])
        left_pwm_channel = int(daemon_env_values["TXING_MOTOR_LEFT_PWM_CHANNEL"])
        right_pwm_channel = int(daemon_env_values["TXING_MOTOR_RIGHT_PWM_CHANNEL"])
        left_dir_gpio = int(daemon_env_values["TXING_MOTOR_LEFT_DIR_GPIO"])
        right_dir_gpio = int(daemon_env_values["TXING_MOTOR_RIGHT_DIR_GPIO"])
        track_width_m = float(daemon_env_values["TXING_MOTOR_TRACK_WIDTH_M"])
        max_wheel_linear_speed_mps = float(
            daemon_env_values["TXING_MOTOR_MAX_WHEEL_LINEAR_SPEED_MPS"]
        )
        left_track_power_percent = float(daemon_env_values["TXING_MOTOR_LEFT_TRACK_POWER_PERCENT"])
        right_track_power_percent = float(
            daemon_env_values["TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT"]
        )
        watchdog_timeout_ms = int(daemon_env_values["TXING_MOTOR_WATCHDOG_TIMEOUT_MS"])

        self.assertGreater(raw_max_speed, 0)
        self.assertGreaterEqual(cmd_raw_min_speed, 0)
        self.assertGreater(cmd_raw_max_speed, 0)
        self.assertLess(cmd_raw_min_speed, cmd_raw_max_speed)
        self.assertLessEqual(cmd_raw_max_speed, raw_max_speed)
        self.assertGreater(pwm_hz, 0)
        self.assertNotEqual(left_pwm_channel, right_pwm_channel)
        self.assertNotEqual(left_dir_gpio, right_dir_gpio)
        self.assertTrue(math.isfinite(track_width_m))
        self.assertGreater(track_width_m, 0.0)
        self.assertTrue(math.isfinite(max_wheel_linear_speed_mps))
        self.assertGreater(max_wheel_linear_speed_mps, 0.0)
        self.assertTrue(math.isfinite(left_track_power_percent))
        self.assertGreater(left_track_power_percent, 0.0)
        self.assertLessEqual(left_track_power_percent, 100.0)
        self.assertTrue(math.isfinite(right_track_power_percent))
        self.assertGreater(right_track_power_percent, 0.0)
        self.assertLessEqual(right_track_power_percent, 100.0)
        self.assertGreater(watchdog_timeout_ms, 0)
        self.assertNotIn("\nBOARD_DRIVE_", "\n" + daemon_env_template)
        self.assertNotIn("\nBOARD_VIDEO_", "\n" + daemon_env_template)
        self.assertNotIn("AWS_STACK_NAME", daemon_justfile)
        self.assertNotIn("DeviceDaemonCredentialRoleAlias", daemon_justfile)

    def test_board_daemon_config_stages_every_openrc_service(self) -> None:
        aws_lib = AWS_DIR / "scripts" / "aws_lib.sh"
        base_files = {
            "daemon.env",
            "certificate.pem.crt",
            "public.pem.key",
            "private.pem.key",
            "certificate.arn",
            "AmazonRootCA1.pem",
            "SFSRootCAG2.pem",
        }
        service_files = {
            "txing-unit-hardware-worker",
            "txing-unit-daemon",
            "txing-tbot-mavlink",
            "txing-tbot-daemon",
            "txing-tbot-ardupilot",
            "txing-kvs-master",
            "txing-cyberbrick-ardupilot",
            "txing-cyberbrick-mavlink",
            "txing-cyberbrick-daemon",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "bundle"
            tarball_path = Path(temp_dir) / "daemon-config.tgz"
            runtime_only_tarball_path = Path(temp_dir) / "runtime-only-config.tgz"
            output_dir.mkdir()
            for name in base_files:
                (output_dir / name).write_text(f"{name}\n", encoding="utf-8")

            subprocess.run(
                [
                    "sh",
                    "-eu",
                    "-c",
                    '. "$1"\n'
                    'txing_cert_stage_board_services "$2" "$3"\n'
                    'txing_cert_write_runtime_tarball "$2" "$4" services\n'
                    'txing_cert_write_runtime_tarball "$2" "$5"',
                    "test-board-services",
                    str(aws_lib),
                    str(output_dir),
                    str(REPO_ROOT / "devices"),
                    str(tarball_path),
                    str(runtime_only_tarball_path),
                ],
                check=True,
                cwd=REPO_ROOT,
            )

            with tarfile.open(tarball_path, "r:gz") as archive:
                members = {member.name.rstrip("/"): member for member in archive}

            self.assertEqual(
                set(members),
                base_files
                | {"services"}
                | {f"services/{name}" for name in service_files},
            )
            for name in service_files:
                self.assertEqual(members[f"services/{name}"].mode, 0o755)

            kvs_script = output_dir / "services" / "txing-kvs-master"
            for service_name, device in (
                ("txing-unit-kvs-master", "unit"),
                ("txing-tbot-kvs-master", "tbot"),
                ("txing-cyberbrick-kvs-master", "cyberbrick"),
            ):
                with self.subTest(service=service_name):
                    resolved = subprocess.run(
                        [
                            "sh",
                            "-eu",
                            "-c",
                            'RC_SVCNAME="$1"\n'
                            '. "$2"\n'
                            'printf \'%s\n%s\n%s\n\' "$device" "$command" "$ca_cert"',
                            "test-kvs-service",
                            service_name,
                            str(kvs_script),
                        ],
                        check=True,
                        text=True,
                        stdout=subprocess.PIPE,
                    )
                    self.assertEqual(
                        resolved.stdout.splitlines(),
                        [
                            device,
                            "/root/.local/share/mise/installs/"
                            "txing-board-kvs-master/latest/"
                            "txing-board-kvs-master",
                            f"/root/.config/txing/{device}-daemon/SFSRootCAG2.pem",
                        ],
                    )

            with tarfile.open(runtime_only_tarball_path, "r:gz") as archive:
                runtime_only_names = {member.name.rstrip("/") for member in archive}
            self.assertEqual(runtime_only_names, base_files)

    def test_aws_cert_recipe_uses_shared_device_daemon_bundle_and_video_policy(self) -> None:
        aws_justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")
        daemon_env_template = (
            REPO_ROOT / "devices" / "common" / "daemon.env.template"
        ).read_text(encoding="utf-8")

        self.assertIn("device_daemon_env_template", aws_justfile)
        self.assertNotIn("mac_daemon_env_template", aws_justfile)
        self.assertNotIn("cyberbrick_daemon_env_template", aws_justfile)
        self.assertIn("deviceType:tbot)", aws_lib)
        self.assertIn("deviceType:cyberbrick)", aws_lib)
        self.assertIn("tbot-daemon", aws_lib)
        self.assertIn('"$device_env_template"', aws_lib)
        self.assertIn("cyberbrick-daemon", aws_lib)
        self.assertIn("DaemonKvsMaster", aws_lib)
        self.assertIn("kinesisvideo:ConnectAsMaster", aws_lib)
        self.assertIn(
            "arn:${partition}:kinesisvideo:${TXING_AWS_REGION}:${account_id}:"
            "channel/${thing_id}-board-video/*",
            aws_lib,
        )
        self.assertIn(
            "arn:${partition}:kinesisvideo:${TXING_AWS_REGION}:${account_id}:"
            "channel/${thing_id}-mavlink/*",
            aws_lib,
        )
        self.assertIn('--arg daemonCapabilities "$daemon_capabilities"', aws_lib)
        self.assertIn(
            'if ($daemonCapabilities | split(",") | index("mavlink")) != null then [$mavlinkChannelArn]',
            aws_lib,
        )
        self.assertNotIn('if $thingType == "cyberbrick" then [$mavlinkChannelArn]', aws_lib)
        self.assertIn(
            "TXING_BOARD_VIDEO_CHANNEL_NAME={{TXING_BOARD_VIDEO_CHANNEL_NAME}}",
            daemon_env_template,
        )
        self.assertIn("TXING_DAEMON_CAPABILITIES={{TXING_DAEMON_CAPABILITIES}}", daemon_env_template)
        self.assertIn("txing_cert_device_daemon_capabilities", aws_lib)
        self.assertIn('index("mcp") != null and index("mavlink") != null', aws_lib)
        self.assertFalse((REPO_ROOT / "devices" / "cyberbrick" / "daemon.env.template").exists())
        self.assertFalse((REPO_ROOT / "devices" / "mac" / "daemon.env.template").exists())

    def test_device_kvs_master_permissions_do_not_change_office_viewer_permissions(self) -> None:
        template = _template_text()

        viewer_statement = template.split("Sid: BoardVideoViewer", 1)[1].split(
            "TxingAdminIdentityPoolRoleAttachment:",
            1,
        )[0]
        self.assertIn("kinesisvideo:ConnectAsViewer", viewer_statement)
        self.assertNotIn("kinesisvideo:ConnectAsMaster", viewer_statement)

        device_statement = template.split("Sid: DeviceKvsMaster", 1)[1].split(
            "TxingRuntimeRole:",
            1,
        )[0]
        self.assertIn("kinesisvideo:ConnectAsMaster", device_statement)
        self.assertNotIn("kinesisvideo:ConnectAsViewer", device_statement)

    def test_template_defines_rig_daemon_credential_resources(self) -> None:
        template = _template_text()

        self.assertIn("TxingRigDaemonCredentialRole:", template)
        self.assertIn("Service: credentials.iot.amazonaws.com", template)
        self.assertIn("TxingRigDaemonCredentialRoleAlias:", template)
        self.assertIn("Type: AWS::IoT::RoleAlias", template)
        self.assertIn("CredentialDurationSeconds: 3600", template)
        self.assertIn("iot:AssumeRoleWithCertificate", template)
        self.assertNotIn("greengrass:*", template)
        self.assertNotIn("TxingGreengrassArtifactsBucket:", template)
        self.assertNotIn("Sid: RigGreengrassArtifactObjectRead", template)
        self.assertNotIn("Sid: RigGreengrassComponentDeploy", template)
        self.assertNotIn("greengrass:CreateComponentVersion", template)
        self.assertNotIn("greengrass:CreateDeployment", template)
        self.assertNotIn("greengrass:ListThingGroupsForCoreDevice", template)
        self.assertNotIn("greengrass:ResolveComponentCandidates", template)
        self.assertNotIn("Sid: RigGreengrassArtifactObjectWrite", template)
        self.assertNotIn("Sid: RigTypeThingGroupDeploy", template)
        self.assertNotIn("thinggroup/txing-rig-type-*", template)
        self.assertIn("RigDaemonCredentialRoleAliasArn:", template)
        self.assertNotIn("GreengrassArtifactsBucketName:", template)

    def test_base_stack_cleans_disposable_buckets_on_delete(self) -> None:
        root_template = _template_text()
        template = _aws_lambda_template_text("aws-clean-stack")

        self.assertIn("CleanStackFunction:", template)
        self.assertIn("FunctionName: !Sub ${EnvironmentStackName}-aws-clean-stack", template)
        self.assertIn(
            "LogGroupName: !Sub /aws/lambda/${EnvironmentStackName}-aws-clean-stack",
            template,
        )
        self.assertIn("Handler: aws_admin.clean_stack.lambda_handler", template)
        self.assertIn("Default: /txing/stack/AwsCleanStackFunctionArn", root_template)
        self.assertIn("ServiceToken: !Ref AwsCleanStackFunctionArn", root_template)
        self.assertIn("Name: /txing/stack/AwsCleanStackFunctionArn", template)
        self.assertNotIn("TxingStackCleanupFunction:", template)
        self.assertNotIn("RetainLegacyCustomResourceFunctionCondition", template)
        self.assertNotIn("FunctionName: town-BaseEnvironment", template)
        self.assertNotIn("FunctionName: aws-clean-stack\n", template)
        self.assertNotIn("LogGroupName: /aws/lambda/aws-clean-stack", template)
        self.assertNotIn("TxingWebBucketCleanup:", template)
        self.assertNotIn("ZipFile: |", template)
        self.assertNotIn("Type: Custom::TxingS3BucketCleanup", template)
        self.assertNotIn("s3:DeleteObjectVersion", template)

    def test_base_stack_does_not_mutate_iot_policy_targets_on_delete(self) -> None:
        template = _template_text()

        self.assertNotIn("AwsCleanStackIotPolicyAttachmentCleanup:", template)
        self.assertNotIn("Type: Custom::TxingIotPolicyAttachmentCleanup", template)
        self.assertNotIn("CleanupType: IotPolicyAttachments", template)
        self.assertNotIn("iot:ListTargetsForPolicy", template)
        self.assertNotIn("iot:DetachPolicy", template)

    def test_base_stack_configures_iot_fleet_indexing(self) -> None:
        template = _template_text()
        clean_template = _aws_lambda_template_text("aws-clean-stack")

        self.assertIn("AwsCleanStackIotFleetIndexing:", template)
        self.assertIn("Type: Custom::TxingIotFleetIndexing", template)
        self.assertIn("CleanupType: IotFleetIndexing", template)
        self.assertIn(
            "PhysicalResourceId: !Sub ${AWS::StackName}-iot-fleet-indexing", template
        )
        self.assertIn("iot:UpdateIndexingConfiguration", clean_template)
        self.assertIn("iot:GetIndexingConfiguration", clean_template)
        self.assertIn("Handler: aws_admin.clean_stack.lambda_handler", clean_template)

    def test_base_stack_custom_resource_manages_type_catalog(self) -> None:
        template = _template_text()
        clean_template = _aws_lambda_template_text("aws-clean-stack")

        self.assertIn("ServiceToken: !Ref AwsCleanStackFunctionArn", template)
        self.assertIn("CleanupType: TypeCatalog", template)
        self.assertIn("iot:CreateThingType", clean_template)
        self.assertIn("iot:DescribeThingType", clean_template)
        self.assertIn("iot:UpdateThingType", clean_template)
        self.assertIn("ssm:PutParameter", clean_template)
        self.assertIn("ssm:DeleteParameter", clean_template)
        self.assertIn("ssm:DeleteParameters", clean_template)
        self.assertIn("ssm:GetParametersByPath", clean_template)
        self.assertIn("cloudformation:DescribeStacks", clean_template)
        self.assertIn("Handler: aws_admin.clean_stack.lambda_handler", clean_template)

    def test_root_stack_owns_type_catalog_and_runtime_layers(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        template = _template_text()
        cloud_rig_template = _cloud_rig_template_text()
        cloud_mcu_lambda_template = _cloud_mcu_lambda_template_text()

        for logical_id in (
            "TownTypeCatalogV2",
            "RaspiTypeCatalogV2",
            "UnitTypeCatalogV2",
            "CyberbrickTypeCatalogV2",
            "WeatherTypeCatalogV2",
            "PowerTypeCatalogV2",
            "CloudTypeCatalogV2",
            "TxingRigRuntimeManagedPolicy",
            "TxingRuntimeManagedPolicy",
        ):
            self.assertIn(f"  {logical_id}:", root_template)

        self.assertIn("  CloudMcuTypeCatalogV2:", cloud_mcu_lambda_template)
        self.assertNotIn("  CloudMcuTypeCatalogV2:", root_template)
        self.assertIn("Type: Custom::TxingTypeCatalog", template)
        self.assertIn("Type: Custom::TxingTypeCatalog", cloud_mcu_lambda_template)
        self.assertIn("ServiceToken: !Ref AwsCleanStackFunctionArn", root_template)
        self.assertIn("ServiceToken: !Ref AwsCleanStackFunctionArn", cloud_mcu_lambda_template)
        self.assertNotIn("Type: AWS::CloudFormation::Stack", root_template)
        self.assertNotIn("Type: AWS::Lambda::Function", root_template)
        self.assertNotIn("Type: AWS::SQS::Queue", root_template)
        self.assertNotIn("Type: AWS::ECS::Cluster", root_template)
        self.assertNotIn("Type: AWS::EC2::VPC", root_template)
        self.assertNotIn("CloudMcuTickQueue:", root_template)
        self.assertNotIn("CloudMcuCluster:", root_template)
        self.assertNotIn("TemplateURL:", root_template)
        self.assertNotIn("LambdaStackMigrationPhase", root_template)
        self.assertNotIn("CreateLambdaStacks", root_template)
        self.assertNotIn("BaseEnvironment.Outputs.CustomResourceServiceToken", root_template)
        self.assertIn("ThingTypeName: town", template)
        self.assertIn("ThingTypeName: raspi", template)
        self.assertIn("ThingTypeName: cloud", template)
        self.assertIn("ThingTypeName: unit", template)
        self.assertIn("ThingTypeName: tbot", template)
        self.assertIn("ThingTypeName: cyberbrick", template)
        self.assertIn("ThingTypeName: power", template)
        self.assertIn("ThingTypeName: power-si", template)
        self.assertIn("ThingTypeName: power-nrf", template)
        self.assertIn("ThingTypeName: local", template)
        self.assertIn("ThingTypeName: mac", template)
        self.assertIn("ThingTypeName: cloud-mcu", cloud_mcu_lambda_template)
        self.assertIn("CloudRigFunction:", cloud_rig_template)
        self.assertIn("CloudMcuFunction:", cloud_mcu_lambda_template)
        self.assertIn("CloudRigNcmdTopicRule:", cloud_rig_template)
        self.assertIn("FROM 'spBv1.0/+/NCMD/+'", cloud_rig_template)
        self.assertIn("CLOUD_RIG_SCHEDULE_NAME", cloud_rig_template)
        self.assertIn("AWS::Scheduler::Schedule", cloud_rig_template)
        self.assertIn("scheduler:GetSchedule", cloud_rig_template)
        self.assertIn("scheduler:UpdateSchedule", cloud_rig_template)
        self.assertNotIn("AWS::Events::Rule", cloud_rig_template)
        self.assertNotIn("events:EnableRule", cloud_rig_template)
        self.assertNotIn("events:DisableRule", cloud_rig_template)
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-cloud-rig", cloud_rig_template
        )
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-cloud-mcu",
            cloud_mcu_lambda_template,
        )
        self.assertIn("S3Key: lambda/txing-cloud-rig-lambda/current/bootstrap.zip", cloud_rig_template)
        self.assertIn("S3Key: lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", cloud_mcu_lambda_template)
        self.assertIn("CatalogBasePath: /txing/town/cloud/cloud-mcu", cloud_mcu_lambda_template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/unit", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/tbot", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/cyberbrick", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/power", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/power-si", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/power-nrf", template)
        self.assertIn("CatalogBasePath: /txing/town/local", template)
        self.assertIn("CatalogBasePath: /txing/town/local/mac", template)
        self.assertIn("kind: deviceType", template)
        tbot_catalog = root_template.split(
            "  TBotTypeCatalogV2:",
            1,
        )[1].split("\n  CyberbrickTypeCatalogV2:", 1)[0]
        for expected in (
            "ThingTypeName: tbot",
            "CatalogBasePath: /txing/town/raspi/tbot",
            "deviceType: tbot",
            "rigType: raspi",
            "capabilities: sparkplug,thread,power,board,mavlink,video",
            "redconCommandLevels: 4,3,2,1",
            "redconRules/4: sparkplug,thread",
            "redconRules/3: sparkplug,thread,power",
            "redconRules/2: sparkplug,thread,power,board,mavlink",
            "redconRules/1: sparkplug,thread,power,board,mavlink,video",
            "shadows/mavlink/schema: aws/mavlink-shadow.schema.json",
            'resources/mavlink/channelName: "{device_id}-mavlink"',
            "web/adapter: web/tbot-adapter.tsx",
            'resources/boardVideo/channelName: "{device_id}-board-video"',
        ):
            self.assertIn(expected, tbot_catalog)
        self.assertIn('"deviceId":"tbot-local"', tbot_catalog)
        self.assertNotIn("redconMetricRules/1", tbot_catalog)
        self.assertNotIn("shadows/mcp/schema", tbot_catalog)
        cyberbrick_catalog = root_template.split(
            "  CyberbrickTypeCatalogV2:",
            1,
        )[1].split("\n  WeatherTypeCatalogV2:", 1)[0]
        for expected in (
            "ThingTypeName: cyberbrick",
            "CatalogBasePath: /txing/town/raspi/cyberbrick",
            "deviceType: cyberbrick",
            "rigType: raspi",
            "capabilities: sparkplug,ble,power,board,mavlink,video",
            "redconCommandLevels: 4,3,2,1",
            "redconRules/4: sparkplug,ble",
            "redconRules/3: sparkplug,ble,power",
            "redconRules/2: sparkplug,ble,power,board,mavlink",
            "redconRules/1: sparkplug,ble,power,board,mavlink,video",
            "shadows/mavlink/schema: aws/mavlink-shadow.schema.json",
            "resources/mavlink/channelName: \"{device_id}-mavlink\"",
            "web/adapter: web/cyberbrick-adapter.tsx",
            'resources/boardVideo/channelName: "{device_id}-board-video"',
        ):
            self.assertIn(expected, cyberbrick_catalog)
        self.assertIn('"deviceId":"cyberbrick-local"', cyberbrick_catalog)
        self.assertNotIn("redconMetricRules/1", cyberbrick_catalog)
        self.assertNotIn("deviceType: unit", cyberbrick_catalog)
        self.assertNotIn("EnlistFunctionName:", root_template)
        self.assertNotIn("EnlistFunctionArn:", root_template)
        self.assertIn("RigTypeCatalogRead", template)
        self.assertIn("ssm:GetParametersByPath", template)

    def test_cloud_mcu_template_defines_event_driven_runtime_resources(self) -> None:
        cloud_infra_template = _template_text()
        cloud_rig_template = _cloud_rig_template_text()
        cloud_mcu_template = _cloud_mcu_lambda_template_text()
        template = "\n".join(
            [cloud_infra_template, cloud_rig_template, cloud_mcu_template]
        )

        self.assertIn("CloudRigFunction:", template)
        self.assertIn("CloudRigNcmdTopicRule:", template)
        self.assertIn("CloudMcuFunction:", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("AWS::Scheduler::Schedule", template)
        self.assertIn("AWS::SQS::Queue", template)
        self.assertIn("AWS::Lambda::EventSourceMapping", template)
        self.assertIn("AWS::IoT::TopicRule", template)
        self.assertIn("AWS::ECS::Cluster", template)
        self.assertIn("AWS::ECS::TaskDefinition", template)
        self.assertIn("AWS::EC2::VPC", template)
        self.assertIn("rate(1 minute)", template)
        self.assertIn("FROM 'spBv1.0/+/DCMD/+/+'", template)
        self.assertIn("WHERE startswith(topic(5), 'cloud-mcu-')", template)
        self.assertIn("CloudMcuDcmdTopicRule:", template)
        self.assertIn("CloudMcuDcmdRulePermission:", template)
        self.assertIn("CLOUD_MCU_TICK_QUEUE_URL", cloud_mcu_template)
        self.assertIn("iot:GetThingShadow", template)
        self.assertIn("iot:UpdateThingShadow", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn("sqs:SendMessage", template)
        self.assertIn("sqs:ReceiveMessage", template)
        self.assertIn("ecs:ListTasks", template)
        self.assertIn("ecs:RunTask", template)
        self.assertIn("ecs:StopTask", template)
        self.assertIn("ecs:TagResource", template)
        self.assertIn("ecs:CreateAction: RunTask", template)
        self.assertIn("iam:PassRole", template)
        self.assertIn("Runtime: provided.al2023", template)
        self.assertIn("Handler: bootstrap", template)
        self.assertIn("Architectures:", template)
        self.assertIn("- arm64", template)
        self.assertIn("RetentionInDays: 14", template)
        self.assertIn("CpuArchitecture: ARM64", template)
        self.assertIn("ecr-public.aws.com/docker/library/alpine:3.20", template)
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-cloud-rig",
            template,
        )
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-cloud-mcu", template
        )
        self.assertIn("S3Bucket: !Ref LambdaArtifactsBucketName", template)
        self.assertIn("S3Key: lambda/txing-cloud-rig-lambda/current/bootstrap.zip", template)
        self.assertIn("S3Key: lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", template)
        self.assertIn("FROM 'spBv1.0/+/NCMD/+'", template)
        self.assertIn("AWS::Scheduler::Schedule", template)
        self.assertIn("scheduler:GetSchedule", template)
        self.assertIn("scheduler:UpdateSchedule", template)
        self.assertNotIn("events:EnableRule", template)
        self.assertNotIn("events:DisableRule", template)
        self.assertNotIn("ThingName:", template)
        self.assertNotIn("THING_NAME", template)
        self.assertNotIn("${ThingName}", template)
        self.assertNotIn("AWS::Serverless::Function", template)
        self.assertNotIn("AWS::DynamoDB::Table", template)
        self.assertNotIn("dynamodb:", template)

    def test_enlist_stack_defines_lambda_and_minimal_permissions(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        enlist_template = _aws_lambda_template_text("aws-enlist-txing")

        self.assertNotIn("EnlistLayer:", root_template)
        self.assertNotIn("TemplateURL: templates/lambdas/aws-enlist-txing.yaml", root_template)
        self.assertIn("EnlistFunction:", enlist_template)
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-aws-enlist-txing", enlist_template
        )
        self.assertIn(
            "LogGroupName: !Sub /aws/lambda/${EnvironmentStackName}-aws-enlist-txing",
            enlist_template,
        )
        self.assertIn("RetentionInDays: 14", enlist_template)
        self.assertIn("Runtime: python3.12", enlist_template)
        self.assertIn("Handler: aws_admin.enlist_txing.lambda_handler", enlist_template)
        self.assertNotIn("Handler: bootstrap", enlist_template)
        self.assertIn("AwsAdminCodeS3Bucket:", enlist_template)
        self.assertIn("AwsAdminCodeS3Key:", enlist_template)
        self.assertIn("S3Bucket: !Ref AwsAdminCodeS3Bucket", enlist_template)
        self.assertIn("S3Key: !Ref AwsAdminCodeS3Key", enlist_template)
        self.assertNotIn("FunctionName: txing-enlist-lambda", enlist_template)
        self.assertNotIn("Legacy service-token bridge", enlist_template)
        self.assertIn("MemorySize: 128", enlist_template)
        self.assertNotIn("AwsEnlistTxingDischargeThingsOnStackDelete:", enlist_template)
        self.assertNotIn("TxingDischargeThingsOnDelete:", enlist_template)
        self.assertNotIn("Type: Custom::TxingDischargeThings", enlist_template)
        self.assertNotIn("CleanupType: TxingDischargeThings", enlist_template)
        self.assertNotIn("EnlistFunctionName:", root_template)
        self.assertNotIn("EnlistFunctionArn:", root_template)
        self.assertIn("EnlistFunctionName:", enlist_template)
        self.assertIn("EnlistFunctionArn:", enlist_template)
        for action in (
            "iot:CreateThing",
            "iot:DeleteThing",
            "iot:DeleteThingShadow",
            "iot:DescribeThing",
            "iot:DetachThingPrincipal",
            "iot:ListThingPrincipals",
            "iot:CreateThingGroup",
            "iot:AddThingToThingGroup",
            "iot:RemoveThingFromThingGroup",
            "iot:ListThingGroupsForThing",
            "iot:UpdateThing",
            "iot:SearchIndex",
            "iot:GetThingShadow",
            "iot:UpdateThingShadow",
            "kinesisvideo:CreateSignalingChannel",
            "kinesisvideo:DescribeSignalingChannel",
            "ssm:GetParametersByPath",
        ):
            self.assertIn(action, enlist_template)
        self.assertNotIn("cloudformation:DescribeStacks", enlist_template)
        self.assertIn("EnlistSignalingChannels", enlist_template)

    def test_rig_runtime_can_connect_with_managed_device_client_ids(self) -> None:
        template = _template_text()

        self.assertIn("Sid: RigMqttConnect", template)
        self.assertIn("client/*", template)
        self.assertIn("thing connectivity", template)

    def test_global_resources_use_deterministic_names(self) -> None:
        template = _template_text()
        cloud_rig_template = _cloud_rig_template_text()
        cloud_mcu_template = _cloud_mcu_lambda_template_text()

        self.assertIn("Type: AWS::IAM::Role", template)
        self.assertIn("Type: AWS::IAM::ManagedPolicy", template)
        self.assertIn("Type: AWS::IoT::RoleAlias", template)
        self.assertIn("Type: AWS::IoT::Policy", template)
        self.assertIn("RoleName: !Sub ${AWS::StackName}-rig-runtime", template)
        self.assertIn("RoleName: !Sub ${AWS::StackName}-device-runtime", template)
        self.assertIn("ManagedPolicyName: !Sub ${AWS::StackName}-rig-runtime", template)
        self.assertIn("ManagedPolicyName: !Sub ${AWS::StackName}-device-runtime", template)
        self.assertIn("PolicyName: !Sub ${AWS::StackName}-gateway", template)
        self.assertIn("PolicyName: !Sub ${AWS::StackName}-web-admin", template)
        self.assertIn("PolicyName: !Sub ${AWS::StackName}-device-daemon", template)
        self.assertIn("RoleAlias: !Sub ${AWS::StackName}-rig-daemon", template)
        self.assertNotIn("QueueName: !Sub ${AWS::StackName}-cloud-mcu-tick", template)
        self.assertNotIn("ClusterName: !Sub ${AWS::StackName}-cloud-mcu", template)
        self.assertIn(
            "QueueName: !Sub ${EnvironmentStackName}-cloud-mcu-tick",
            cloud_mcu_template,
        )
        self.assertIn(
            "ClusterName: !Sub ${EnvironmentStackName}-cloud-mcu",
            cloud_mcu_template,
        )
        self.assertIn("Name: /txing/stack/CloudMcuTickQueueUrl", cloud_mcu_template)
        self.assertIn("Name: /txing/stack/CloudMcuRuntimeFunctionArn", cloud_mcu_template)
        self.assertIn("Default: /txing/stack/CloudMcuTickQueueUrl", cloud_rig_template)
        self.assertIn("Default: /txing/stack/CloudMcuTickQueueArn", cloud_rig_template)
        self.assertNotIn(
            "stack_output",
            (REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "justfile").read_text(
                encoding="utf-8"
            ),
        )

    def test_root_template_uses_single_stack_resources(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")

        self.assertNotIn("Type: AWS::CloudFormation::Stack", root_template)
        self.assertNotIn("TemplateURL:", root_template)
        self.assertIn("TxingGatewayLogsManagedPolicy:", root_template)
        self.assertNotIn("AWS::Lambda::Function", root_template)

    def test_root_template_defines_release_publisher_lambda(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        publish_template = _aws_lambda_template_text("aws-publish-release")
        template = root_template

        self.assertNotIn("PublishReleaseLayer:", root_template)
        self.assertNotIn("TemplateURL: templates/lambdas/aws-publish-release.yaml", root_template)
        self.assertIn("PublishReleaseFunction", publish_template)
        self.assertIn(
            "FunctionName: !Sub ${EnvironmentStackName}-aws-publish-release",
            publish_template,
        )
        self.assertIn("Runtime: python3.12", publish_template)
        self.assertIn("Handler: aws_admin.publish_release.handler.lambda_handler", publish_template)
        self.assertIn("AwsAdminCodeS3Bucket:", publish_template)
        self.assertIn("AwsAdminCodeS3Key:", publish_template)
        self.assertIn("S3Bucket: !Ref AwsAdminCodeS3Bucket", publish_template)
        self.assertIn("S3Key: !Ref AwsAdminCodeS3Key", publish_template)
        self.assertIn("TXING_GITHUB_REPOSITORY", publish_template)
        self.assertIn("TXING_LAMBDA_ARTIFACT_BUCKET", publish_template)
        self.assertIn("TXING_LAMBDA_FUNCTIONS_JSON", publish_template)
        self.assertNotIn("TXING_LAMBDA_FUNCTION_PREFIX", publish_template)
        self.assertNotIn("TXING_GREENGRASS_ARTIFACT_BUCKET", publish_template)
        self.assertNotIn("ReleasePublisherFunctionName", root_template)
        self.assertNotIn("ReleasePublisherFunctionArn", root_template)
        self.assertIn("ReleasePublisherFunctionName", publish_template)
        self.assertIn("ReleasePublisherFunctionArn", publish_template)
        self.assertIn("Name: /txing/stack/ReleasePublisherFunctionName", publish_template)
        self.assertIn("Default: /txing/stack/WitnessFunctionArn", publish_template)
        self.assertIn("Default: /txing/stack/WitnessFunctionName", publish_template)
        self.assertIn("Default: /txing/stack/CloudRigRuntimeFunctionArn", publish_template)
        self.assertIn("Default: /txing/stack/CloudRigRuntimeFunctionName", publish_template)
        self.assertIn("Default: /txing/stack/CloudMcuRuntimeFunctionArn", publish_template)
        self.assertIn("Default: /txing/stack/CloudMcuRuntimeFunctionName", publish_template)
        self.assertIn("- !Ref WitnessFunctionArn", publish_template)
        self.assertNotIn("function:${EnvironmentStackName}-witness", publish_template)
        for action in (
            "lambda:UpdateFunctionCode",
            "lambda:GetFunction",
            "lambda:GetFunctionConfiguration",
            "s3:PutObject",
            "s3:GetObject",
            "s3:AbortMultipartUpload",
            "s3:ListMultipartUploadParts",
            "s3:ListBucketMultipartUploads",
        ):
            self.assertIn(action, publish_template)
        for action in (
            "greengrass:CreateComponentVersion",
            "greengrass:CreateDeployment",
            "greengrass:DeleteComponent",
            "greengrass:ListComponents",
            "greengrass:ListComponentVersions",
            "iot:CreateThingGroup",
            "iot:CreateJob",
            "iot:UpdateJob",
        ):
            self.assertNotIn(action, publish_template)
        self.assertNotIn("Sid: CreateGreengrassDeploymentJobs", publish_template)
        self.assertNotIn("thinggroup/txing-rig-type-*", publish_template)
        self.assertNotIn("job/*", publish_template)
        self.assertNotIn("FunctionUrlConfig", template)
        self.assertNotIn("GITHUB_TOKEN", template)

    def test_cloud_mcu_runtime_uses_release_lambda_assets(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        cloud_mcu_template = _cloud_mcu_lambda_template_text()
        lambda_templates = "\n".join(
            [_cloud_rig_template_text(), _cloud_mcu_lambda_template_text()]
        )
        cloud_mcu_source = (
            REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "internal" / "cloudmcu" / "cloudmcu.go"
        ).read_text(encoding="utf-8")
        aws_justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        root_justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

        removed_version_env = "TXING_" + "VERSION"
        self.assertFalse((REPO_ROOT / "VERSION").exists())
        self.assertNotIn("_project-" + "version-env:", root_justfile)
        self.assertNotIn(removed_version_env + "_BASE", root_justfile)
        self.assertNotIn("export_line " + removed_version_env, root_justfile)
        self.assertIn("_project-git-env:", root_justfile)
        parameter_block = root_template.split("\nResources:", 1)[0]
        self.assertIn("StackCognitoDomainPrefix:", parameter_block)
        self.assertIn("StackAdminEmail:", parameter_block)
        self.assertIn("StackWebAppUrl:", parameter_block)
        self.assertNotIn("  CognitoDomainPrefix:\n", parameter_block)
        self.assertNotIn("  AdminEmail:\n", parameter_block)
        self.assertNotIn("  WebAppUrl:\n", parameter_block)
        self.assertIn("Type: AWS::SSM::Parameter::Value<String>", root_template)
        self.assertIn("Default: /txing/stack/CognitoDomainPrefix", root_template)
        self.assertIn("Default: /txing/stack/AdminEmail", root_template)
        self.assertIn("Default: /txing/stack/WebAppUrl", root_template)
        self.assertIn(
            "Description: SSM parameter containing the seed admin email used by the bootstrap admin-user helper.",
            root_template,
        )
        self.assertNotIn("single admin email expected by the SPA", root_template)
        for parameter_name in (
            "WebCognitoDomain",
            "WebCognitoUserPoolClientId",
            "WebCognitoUserPoolId",
            "WebCognitoIdentityPoolId",
            "WebIotPolicyName",
            "WebExpectedAdminEmail",
            "RigRuntimeManagedPolicyArn",
            "DeviceDaemonIotPolicyName",
        ):
            self.assertIn(f"Name: /txing/stack/{parameter_name}", root_template)
        self.assertIn("Domain: !Ref StackCognitoDomainPrefix", root_template)
        self.assertIn("seed-admin-email: !Ref StackAdminEmail", root_template)
        self.assertIn(
            "Description: Seed admin email for the bootstrap admin-user helper; not an office allow-list.",
            root_template,
        )
        self.assertIn('!Sub "${StackWebAppUrl}/"', root_template)
        self.assertNotIn("TemplateURL:", root_template)
        self.assertIn("Runtime: provided.al2023", lambda_templates)
        self.assertIn("Handler: bootstrap", lambda_templates)
        self.assertIn("- arm64", lambda_templates)
        self.assertIn("lambda/txing-cloud-rig-lambda/current/bootstrap.zip", lambda_templates)
        self.assertIn("lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", lambda_templates)
        self.assertIn("Type: AWS::EC2::VPCCidrBlock", cloud_mcu_template)
        self.assertIn("AmazonProvidedIpv6CidrBlock: true", cloud_mcu_template)
        self.assertIn("Type: AWS::EC2::EgressOnlyInternetGateway", cloud_mcu_template)
        self.assertIn("Ipv6Native: true", cloud_mcu_template)
        self.assertIn("AssignIpv6AddressOnCreation: true", cloud_mcu_template)
        self.assertIn("EnableResourceNameDnsAAAARecord: true", cloud_mcu_template)
        self.assertIn("EnableResourceNameDnsARecord: false", cloud_mcu_template)
        self.assertIn("HostnameType: resource-name", cloud_mcu_template)
        self.assertIn("DestinationIpv6CidrBlock: ::/0", cloud_mcu_template)
        self.assertIn(
            "EgressOnlyInternetGatewayId: !Ref CloudMcuEgressOnlyInternetGateway",
            cloud_mcu_template,
        )
        self.assertIn("CidrIpv6: ::/0", cloud_mcu_template)
        self.assertNotIn("Type: AWS::EC2::InternetGateway", cloud_mcu_template)
        self.assertNotIn("Type: AWS::EC2::VPCGatewayAttachment", cloud_mcu_template)
        self.assertNotIn("CidrBlock: 10.83.0.0/25", cloud_mcu_template)
        self.assertNotIn("MapPublicIpOnLaunch", cloud_mcu_template)
        self.assertNotIn("DestinationCidrBlock: 0.0.0.0/0", cloud_mcu_template)
        self.assertNotIn("CidrIp: 0.0.0.0/0", cloud_mcu_template)
        self.assertNotIn("Type: AWS::ECR::Repository", cloud_mcu_template)
        self.assertNotIn("CloudMcuContainerRepositoryDualStackUri", cloud_mcu_template)
        self.assertNotIn("ecr:GetAuthorizationToken", cloud_mcu_template)
        self.assertIn("AssignPublicIp: ecstypes.AssignPublicIpDisabled", cloud_mcu_source)
        self.assertNotIn("AssignPublicIp: ecstypes.AssignPublicIpEnabled", cloud_mcu_source)
        self.assertNotIn("--parameter-overrides", aws_justfile)

    def test_web_hosting_is_external_to_aws_stack(self) -> None:
        template = _template_text()
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")

        self.assertNotIn("AWS::CloudFront::Distribution", template)
        self.assertNotIn("AWS::CloudFront::OriginAccessControl", template)
        self.assertNotIn("TxingWebBucket:", template)
        self.assertNotIn("WebAppBucketName:", template)
        self.assertNotIn("WebAppDistributionId:", template)
        self.assertNotIn("WebAppBucketName:", root_template)
        self.assertNotIn("WebAppDistributionId:", root_template)
        self.assertNotIn('Default: https://office.txing.dev', root_template)
        self.assertIn("Default: /txing/stack/WebAppUrl", template)
        self.assertIn('- !Sub "${StackWebAppUrl}/"', template)
        self.assertIn("- https://txing.dev/", template)

    def test_static_manifests_use_plain_semver_only(self) -> None:
        manifest_paths = [
            REPO_ROOT / "shared" / "aws" / "python" / "pyproject.toml",
            REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "go.mod",
            REPO_ROOT / "witness" / "go.mod",
            REPO_ROOT / "rig" / "go.mod",
            REPO_ROOT / "office" / "package.json",
        ]
        for path in manifest_paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("+g", text, path)
            self.assertNotIn(".dirty", text, path)

    def test_aws_recipes_are_stateless_and_staged(self) -> None:
        checked_paths = [
            REPO_ROOT / "justfile",
            REPO_ROOT / "release" / "justfile",
            AWS_DIR / "justfile",
            AWS_DIR / "scripts" / "aws_lib.sh",
            REPO_ROOT / "devices" / "cloud-mcu" / "justfile",
            REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "justfile",
            REPO_ROOT / "devices" / "common" / "board" / "justfile",
            REPO_ROOT / "office" / "justfile",
            REPO_ROOT / "rig" / "justfile",
            REPO_ROOT / "witness" / "justfile",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

        self.assertIn("deploy-init parameter_file", text)
        self.assertIn("delete-init:", text)
        self.assertIn("aws ssm put-parameter", text)
        self.assertIn("aws ssm delete-parameter", text)
        self.assertIn("deploy_init_parameter_name()", text)
        self.assertIn("/txing/stack", text)
        self.assertIn("deploy stack_name=stack_name", text)
        self.assertIn("_deploy-clean-stack stack_name=stack_name", text)
        self.assertIn("_deploy-enlist-lambda stack_name=stack_name", text)
        self.assertIn("_deploy-publish-release-lambda stack_name=stack_name", text)
        self.assertNotIn("deploy-local-lambda", text)
        self.assertNotIn("deploy-lambda-drain", text)
        self.assertNotIn("deploy-lambda-migrate", text)
        self.assertNotIn("clean-stack::deploy", text)
        self.assertNotIn("enlist-lambda::deploy", text)
        self.assertNotIn("publish-release-lambda::deploy", text)
        self.assertNotIn("LambdaStackMigrationPhase", text)
        self.assertIn('--s3-bucket "$artifact_bucket"', text)
        self.assertIn("--capabilities CAPABILITY_NAMED_IAM", text)
        self.assertIn("upload_packaged_template()", text)
        self.assertIn('template_url="$(upload_packaged_template "$artifact_bucket" "$packaged_template")"', text)
        self.assertIn('aws cloudformation validate-template --template-url "$template_url"', text)
        self.assertIn('lambda_artifacts_bucket_parameter="LambdaArtifactsBucketName=$artifact_bucket"', text)
        self.assertIn("set -- --parameter-overrides", text)
        self.assertIn('aws_admin_code_bucket_parameter="AwsAdminCodeS3Bucket=$artifact_bucket"', text)
        self.assertIn("describe_stack_parameters()", text)
        self.assertIn("stack_parameter()", text)
        self.assertIn("preflight_named_log_groups()", text)
        self.assertIn("CloudFormation cannot create stack", text)
        self.assertIn("--output json | jq 'sort_by(.Name)'", text)
        self.assertNotIn("--output table", text)
        self.assertNotIn("Outputs[?OutputKey", text)
        self.assertNotIn("deploy CognitoDomainPrefix", text)
        self.assertIn("aws ssm get-parameter", text)
        self.assertIn("deploy-town town_name", text)
        self.assertIn("deploy-rig town_id", text)
        self.assertIn("deploy-device rig_id", text)
        self.assertIn("enlist payload_file", text)
        self.assertIn("discharge thing_id", text)
        self.assertIn("delete stack_name", text)
        self.assertIn("aws lambda invoke", text)
        self.assertIn("aws cloudformation delete-stack", text)
        self.assertIn("stack-delete-complete", text)
        self.assertNotIn("stack_output \"$TXING_AWS_STACK\" EnlistFunctionName", text)
        self.assertIn('function_name="$(stack_parameter EnlistFunctionName)"', text)
        self.assertNotIn("stack_output()", text)
        self.assertIn("resolve_town_thing_name()", text)
        self.assertIn("resolve_rig_thing_name()", text)
        self.assertIn("resolve_device_thing_name()", text)
        self.assertNotIn("assume_stack_role()", text)
        self.assertIn("delete-packaging-buckets stack_name", text)
        self.assertIn("delete_s3_bucket_if_exists", text)
        self.assertNotIn("@deploy-lambda", text)
        self.assertNotIn(".state", text)
        self.assertNotIn("local_state_dir", text)
        self.assertNotIn("packaged_template_file", text)
        self.assertNotIn("python -m aws.type_catalog \\\n      --region \"$AWS_REGION\" \\\n      sync", text)
        self.assertNotIn("python -m aws.device_registry", text)
        self.assertNotIn("ensure-town", text)
        self.assertNotIn("ensure-rig", text)
        self.assertNotIn("ensure-device", text)

    def test_aws_cert_recipe_dispatches_generic_and_rig_bundles(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")
        rig_env_template = (REPO_ROOT / "rig" / "rig-daemon.env.template").read_text(
            encoding="utf-8"
        )
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("cert thing_id='':", justfile)
        self.assertIn("txing_generate_iot_certificate_bundle", justfile)
        self.assertNotIn("greengrass-config", justfile)
        self.assertIn("case \"$thing_kind:$thing_type\" in", aws_lib)
        self.assertIn("rigType:raspi | rigType:local)", aws_lib)
        self.assertIn("deviceType:unit)", aws_lib)
        self.assertIn("deviceType:tbot)", aws_lib)
        self.assertIn("deviceType:cyberbrick)", aws_lib)
        self.assertIn("deviceType:mac)", aws_lib)
        self.assertIn("txing_cert_generate_generic_bundle", aws_lib)
        self.assertIn("PolicyName", aws_lib)
        self.assertIn("RigRuntimeManagedPolicyArn", aws_lib)
        self.assertIn('daemon_role_name="txing-rig-daemon-$thing_id"', aws_lib)
        self.assertIn('iot_role_alias="txing-rig-daemon-$thing_id"', aws_lib)
        self.assertIn("credentials.iot.amazonaws.com", aws_lib)
        self.assertIn("--endpoint-type iot:CredentialProvider", aws_lib)
        self.assertIn("--endpoint-type iot:Data-ATS", aws_lib)
        self.assertIn("create-role-alias", aws_lib)
        self.assertIn("create-keys-and-certificate", aws_lib)
        self.assertIn("attach-thing-principal", aws_lib)
        self.assertIn("--thing-principal-type EXCLUSIVE_THING", aws_lib)
        self.assertIn("https://www.amazontrust.com/repository/AmazonRootCA1.pem", aws_lib)
        self.assertIn("https://www.amazontrust.com/repository/SFSRootCAG2.pem", aws_lib)
        self.assertIn("SFSRootCAG2.pem", aws_lib)
        self.assertIn("Certificate or daemon material already exists", aws_lib)
        self.assertIn("__TXING_IOT_ROLE_ALIAS__", rig_env_template)
        self.assertIn("TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock", rig_env_template)
        self.assertIn("TXING_SPARKPLUG_MANAGER_ENABLED=true", rig_env_template)
        self.assertIn("TXING_BLE_CONNECTIVITY_ENABLED=false", rig_env_template)
        self.assertIn("TXING_THREAD_CONNECTIVITY_ENABLED=false", rig_env_template)
        self.assertIn("TXING_BLE_NO_RADIO=false", rig_env_template)
        self.assertNotIn("TXING_BLE_NO_BLE", rig_env_template)
        self.assertIn("TXING_CLOUDWATCH_LOG_GROUP=__TXING_CLOUDWATCH_LOG_GROUP__", rig_env_template)
        self.assertIn("/certs/", gitignore)

    def test_shadow_recipes_resolve_rig_town_or_device_ids_directly(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")

        self.assertIn("txing_resolve_requested_thing_id()", aws_lib)
        self.assertIn("TXING_THING_ID", aws_lib)
        self.assertIn("TXING_RIG_ID", aws_lib)
        self.assertIn("TXING_TOWN_ID", aws_lib)
        for recipe_name in ("shadow ", "shadow-reset ", "init-shadow "):
            recipe = justfile.split(recipe_name, 1)[1].split("\n\n", 1)[0]
            self.assertIn('effective_thing_name="$(txing_resolve_requested_thing_id "{{thing_name}}")"', recipe)
            self.assertIn('_project-aws-env aws', recipe)
            self.assertNotIn('_project-aws-env device', recipe)
            self.assertNotIn("THING_NAME", recipe)

    def test_aws_justfile_enables_thing_connectivity_indexing(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        deploy_recipe = justfile.split("deploy ", 1)[1].split("\n\n", 1)[0]
        configure_recipe = justfile.split("configure-indexing:", 1)[1].split("\n\n", 1)[0]
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")

        self.assertNotIn("configure_indexing_and_wait", deploy_recipe)
        self.assertIn("configure-indexing:", justfile)
        self.assertIn("configure_indexing_and_wait", configure_recipe)
        self.assertIn('"thingConnectivityIndexingMode":"STATUS"', aws_lib)
        self.assertIn('[ "$thing_connectivity_indexing_mode" = "STATUS" ]', aws_lib)
        self.assertNotIn('"thingConnectivityIndexingMode":"OFF"', aws_lib)
        self.assertNotIn("REGISTRY/OFF", aws_lib)


if __name__ == "__main__":
    unittest.main()
