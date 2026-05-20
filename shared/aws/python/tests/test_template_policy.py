from __future__ import annotations

import math
from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


def _template_text() -> str:
    template_paths = [AWS_DIR / "template.yaml"]
    template_paths.extend(sorted((AWS_DIR / "templates").glob("*.yaml")))
    template_paths.extend(sorted((AWS_DIR / "templates" / "types").glob("*.yaml")))
    return "\n".join(path.read_text(encoding="utf-8") for path in template_paths)


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

    def test_base_nested_template_embeds_sparkplug_witness_projection(self) -> None:
        template = _template_text()

        self.assertIn("TxingSparkplugWitnessFunction", template)
        self.assertIn("TxingSparkplugWitnessTopicRule", template)
        self.assertIn("TxingSparkplugWitnessInvokePermission", template)
        self.assertIn("TxingWitnessLogGroup", template)
        self.assertIn("LogGroupName: /aws/lambda/txing-witness-lambda", template)
        self.assertIn("RetentionInDays: 14", template)
        self.assertIn("sparkplug-witness", template)
        self.assertIn("Sid: WitnessShadowUpdate", template)
        self.assertIn("- iot:GetThingShadow", template)
        self.assertIn("- iot:UpdateThingShadow", template)
        self.assertIn("Sid: WitnessDescribeThings", template)
        self.assertIn("Action: iot:DescribeThing", template)
        self.assertIn("Runtime: provided.al2023", template)
        self.assertIn("Handler: rust.handler", template)
        self.assertIn("Architectures:", template)
        self.assertIn("- arm64", template)
        self.assertIn("FunctionName: txing-witness-lambda", template)
        self.assertIn("MemorySize: 128", template)
        self.assertIn("LambdaArtifactsBucketName:", template)
        self.assertIn("S3Bucket: !Ref LambdaArtifactsBucketName", template)
        self.assertIn("S3Key: lambda/txing-witness-lambda/current/bootstrap.zip", template)
        self.assertNotIn("witness/target/lambda/txing-witness-lambda/bootstrap.zip", template)
        self.assertIn("encode(*, 'base64')", template)
        self.assertIn("iot:DescribeEndpoint", template)
        self.assertIn("WitnessFunctionName:", template)
        self.assertIn("WitnessFunctionArn:", template)

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

    def test_unit_daemon_cert_recipe_uses_daemon_specific_outputs(self) -> None:
        unit_justfile = (REPO_ROOT / "devices" / "unit" / "justfile").read_text(
            encoding="utf-8"
        )
        daemon_justfile = (
            REPO_ROOT / "devices" / "unit" / "daemon" / "justfile"
        ).read_text(encoding="utf-8")
        daemon_env_template = (
            REPO_ROOT / "devices" / "unit" / "daemon" / "daemon.env.template"
        ).read_text(encoding="utf-8")
        root_gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("mod daemon 'daemon/justfile'", unit_justfile)
        self.assertIn("cert thing_id=", unit_justfile)
        self.assertIn("daemon::cert", unit_justfile)
        self.assertIn("DeviceDaemonIotPolicyName", daemon_justfile)
        self.assertIn('requested_thing_name="{{thing_id}}"', daemon_justfile)
        self.assertIn("Do not pass just recipe arguments as name=value", daemon_justfile)
        self.assertIn("Use: just unit::cert <thing-id>", daemon_justfile)
        self.assertIn('effective_thing_name="${requested_thing_name:-$THING_NAME}"', daemon_justfile)
        self.assertIn('[[ ! "$effective_thing_name" =~ ^[a-zA-Z0-9:_-]+$ ]]', daemon_justfile)
        self.assertIn("daemon_role_name=\"txing-daemon-$effective_thing_name\"", daemon_justfile)
        self.assertIn("iot_role_alias=\"txing-daemon-$effective_thing_name\"", daemon_justfile)
        self.assertIn("credentials.iot.amazonaws.com", daemon_justfile)
        self.assertIn("DaemonSparkplugShadowRead", daemon_justfile)
        self.assertIn("arn:${partition}:iot:${TXING_AWS_REGION}:${account_id}:thing/${effective_thing_name}/sparkplug", daemon_justfile)
        self.assertIn('cloudwatch_log_group="txing/${TXING_TOWN_ID}/${TXING_RIG_ID}/${effective_thing_name}"', daemon_justfile)
        self.assertIn("DaemonCloudWatchLogsWrite", daemon_justfile)
        self.assertIn("logs:CreateLogGroup", daemon_justfile)
        self.assertIn("logs:CreateLogStream", daemon_justfile)
        self.assertIn("logs:DescribeLogStreams", daemon_justfile)
        self.assertIn("DaemonBoardVideoMaster", daemon_justfile)
        self.assertIn("kinesisvideo:ConnectAsMaster", daemon_justfile)
        self.assertIn("arn:${partition}:kinesisvideo:${TXING_AWS_REGION}:${account_id}:channel/${effective_thing_name}-board-video/*", daemon_justfile)
        self.assertIn('role-policy thing_id=', daemon_justfile)
        self.assertIn("logs:PutRetentionPolicy", daemon_justfile)
        self.assertIn("logs:PutLogEvents", daemon_justfile)
        self.assertIn("arn:${partition}:logs:${TXING_AWS_REGION}:${account_id}:log-group:${cloudwatch_log_group}", daemon_justfile)
        self.assertIn("arn:${partition}:logs:${TXING_AWS_REGION}:${account_id}:log-group:${cloudwatch_log_group}:log-stream:*", daemon_justfile)
        self.assertIn("create-role-alias", daemon_justfile)
        self.assertIn("put-role-policy", daemon_justfile)
        self.assertIn("create-keys-and-certificate", daemon_justfile)
        self.assertIn("attach-policy --policy-name \"$daemon_policy_name\"", daemon_justfile)
        self.assertIn("attach-thing-principal", daemon_justfile)
        self.assertIn("--thing-principal-type EXCLUSIVE_THING", daemon_justfile)
        self.assertIn("TXING_DAEMON_CONFIG_DIR", daemon_justfile)
        self.assertIn('default_output_root() {', daemon_justfile)
        self.assertIn('{{project_root}}/config/certs/unit/$effective_thing_name', daemon_justfile)
        self.assertIn('${effective_thing_name}-daemon-config.tgz', daemon_justfile)
        self.assertIn('COPYFILE_DISABLE=1 tar -C "$output_root" -czf "$tarball_path"', daemon_justfile)
        self.assertIn("configTarball", daemon_justfile)
        self.assertIn("/config/certs/", root_gitignore)
        self.assertIn('env_file="$daemon_config_dir/daemon.env"', daemon_justfile)
        self.assertIn('daemon_env_template="{{daemon_env_template}}"', daemon_justfile)
        self.assertIn("render_daemon_env_template >\"$env_file\"", daemon_justfile)
        self.assertIn('cert_path="$daemon_config_dir/certificate.pem.crt"', daemon_justfile)
        self.assertIn(
            'video_channel_name="${TXING_BOARD_VIDEO_CHANNEL_NAME:-${effective_thing_name}-board-video}"',
            daemon_justfile,
        )
        self.assertIn("export TXING_KVS_MASTER_COMMAND=txing-board-kvs-master", daemon_env_template)
        self.assertIn("export TXING_BOARD_VIDEO_CHANNEL_NAME={{TXING_BOARD_VIDEO_CHANNEL_NAME}}", daemon_env_template)
        self.assertIn("export AWS_REGION={{AWS_REGION}}", daemon_env_template)
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
        self.assertNotIn("export BOARD_DRIVE_", daemon_env_template)
        self.assertNotIn("export BOARD_VIDEO_", daemon_env_template)
        self.assertNotIn("AWS_STACK_NAME", daemon_justfile)
        self.assertNotIn("DeviceDaemonCredentialRoleAlias", daemon_justfile)

    def test_template_defines_greengrass_token_exchange_resources(self) -> None:
        template = _template_text()

        self.assertIn("TxingGreengrassTokenExchangeRole:", template)
        self.assertIn("Service: credentials.iot.amazonaws.com", template)
        self.assertIn("TxingGreengrassTokenExchangeRoleAlias:", template)
        self.assertIn("Type: AWS::IoT::RoleAlias", template)
        self.assertIn("CredentialDurationSeconds: 3600", template)
        self.assertIn("iot:AssumeRoleWithCertificate", template)
        self.assertNotIn("greengrass:*", template)
        self.assertIn("TxingGreengrassArtifactsBucket:", template)
        self.assertIn("Sid: RigGreengrassArtifactObjectRead", template)
        self.assertIn("Sid: RigGreengrassComponentDeploy", template)
        self.assertIn("greengrass:CreateComponentVersion", template)
        self.assertIn("greengrass:CreateDeployment", template)
        self.assertIn("greengrass:ListThingGroupsForCoreDevice", template)
        self.assertIn("greengrass:ResolveComponentCandidates", template)
        self.assertIn("Sid: RigGreengrassArtifactObjectWrite", template)
        self.assertIn("s3:PutObject", template)
        self.assertIn("Sid: RigTypeThingGroupDeploy", template)
        self.assertIn("thinggroup/txing-rig-type-*", template)
        self.assertIn("GreengrassTokenExchangeRoleAliasArn:", template)
        self.assertIn("GreengrassArtifactsBucketName:", template)

    def test_base_stack_cleans_disposable_buckets_on_delete(self) -> None:
        template = _template_text()

        self.assertIn("TxingStackCleanupFunction:", template)
        self.assertIn("Type: Custom::TxingS3BucketCleanup", template)
        self.assertIn("TxingGreengrassArtifactsBucketCleanup:", template)
        self.assertNotIn("TxingWebBucketCleanup:", template)
        self.assertIn('paginator = s3.get_paginator("list_object_versions")', template)
        self.assertIn('object_paginator = s3.get_paginator("list_objects_v2")', template)
        self.assertIn("s3:DeleteObjectVersion", template)

    def test_base_stack_detaches_iot_policy_targets_on_delete(self) -> None:
        template = _template_text()

        self.assertIn("TxingIotPolicyAttachmentCleanup:", template)
        self.assertIn("Type: Custom::TxingIotPolicyAttachmentCleanup", template)
        self.assertIn("CleanupType: IotPolicyAttachments", template)
        self.assertIn("iot:ListTargetsForPolicy", template)
        self.assertIn("iot:DetachPolicy", template)
        self.assertIn("iot.list_targets_for_policy", template)
        self.assertIn("iot.detach_policy", template)

    def test_base_stack_configures_iot_fleet_indexing(self) -> None:
        template = _template_text()

        self.assertIn("TxingIotFleetIndexing:", template)
        self.assertIn("Type: Custom::TxingIotFleetIndexing", template)
        self.assertIn("CleanupType: IotFleetIndexing", template)
        self.assertIn("PhysicalResourceId: txing-iot-fleet-indexing", template)
        self.assertIn("iot:UpdateIndexingConfiguration", template)
        self.assertIn("iot:GetIndexingConfiguration", template)
        self.assertIn("iot.update_indexing_configuration", template)
        self.assertIn('configuration.get("thingIndexingMode") == "REGISTRY"', template)
        self.assertIn(
            'configuration.get("thingConnectivityIndexingMode") == "STATUS"',
            template,
        )
        self.assertIn('"attributes.name"', template)
        self.assertIn('"attributes.kind"', template)
        self.assertIn('"attributes.townId"', template)
        self.assertIn('"attributes.rigId"', template)
        self.assertNotIn('"attributes.rigType"', template)
        self.assertNotIn('"attributes.deviceType"', template)

    def test_base_stack_custom_resource_manages_type_catalog(self) -> None:
        template = _template_text()

        self.assertIn("CustomResourceServiceToken:", template)
        self.assertIn("CleanupType: TypeCatalog", template)
        self.assertIn("iot:CreateThingType", template)
        self.assertIn("iot:DescribeThingType", template)
        self.assertIn("iot:UpdateThingType", template)
        self.assertIn("ssm:PutParameter", template)
        self.assertIn("ssm:DeleteParameter", template)
        self.assertIn("ssm:GetParametersByPath", template)
        self.assertIn("iot.create_thing_type", template)
        self.assertIn("iot.update_thing_type", template)
        self.assertIn("ssm.get_parameters_by_path", template)
        self.assertIn("parameter_names.add(normalized_base_path)", template)
        self.assertIn("ssm.put_parameter", template)
        self.assertIn("SSM_THROTTLE_ERROR_CODES", template)
        self.assertIn("_ssm_call", template)
        self.assertIn("existing_parameters.get(name) == value_text", template)
        self.assertIn("Overwrite=True", template)

    def test_root_stack_owns_type_catalog_and_runtime_layers(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        template = _template_text()

        for logical_id in (
            "TownTypeCatalog",
            "RaspiTypeCatalog",
            "RaspiUnitTypeCatalog",
            "RaspiPowerTypeCatalog",
            "CloudTypeCatalog",
            "CloudMcuTypeCatalog",
            "EnlistLayer",
            "RigRuntimeLayer",
            "DeviceRuntimeLayer",
        ):
            self.assertIn(f"  {logical_id}:", root_template)
        for template_url in (
            "templates/types/town.yaml",
            "templates/types/raspi.yaml",
            "templates/types/raspi-unit.yaml",
            "templates/types/raspi-power.yaml",
            "templates/types/cloud.yaml",
            "templates/types/cloud-mcu.yaml",
            "templates/enlist.yaml",
            "templates/rig.yaml",
            "templates/device.yaml",
        ):
            self.assertIn(f"TemplateURL: {template_url}", root_template)

        self.assertIn("Type: Custom::TxingTypeCatalog", template)
        self.assertIn(
            "TypeCatalogServiceToken: !GetAtt BaseEnvironment.Outputs.CustomResourceServiceToken",
            root_template,
        )
        self.assertIn("ThingTypeName: town", template)
        self.assertIn("ThingTypeName: raspi", template)
        self.assertIn("ThingTypeName: cloud", template)
        self.assertIn("ThingTypeName: unit", template)
        self.assertIn("ThingTypeName: power", template)
        self.assertIn("ThingTypeName: cloud-mcu", template)
        self.assertIn("CloudRigRuntimeFunction:", template)
        self.assertIn("CloudMcuRuntimeFunction:", template)
        self.assertIn("FunctionName: txing-cloud-rig-lambda", template)
        self.assertIn("FunctionName: txing-cloud-mcu-lambda", template)
        self.assertIn("S3Key: lambda/txing-cloud-rig-lambda/current/bootstrap.zip", template)
        self.assertIn("S3Key: lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", template)
        self.assertIn("CatalogBasePath: /txing/town/cloud/cloud-mcu", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/unit", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/power", template)
        self.assertIn("kind: deviceType", template)
        self.assertIn("EnlistFunctionName:", root_template)
        self.assertIn("EnlistFunctionArn:", root_template)
        self.assertIn("RigTypeCatalogRead", template)
        self.assertIn("ssm:GetParametersByPath", template)

    def test_cloud_mcu_template_defines_event_driven_runtime_resources(self) -> None:
        template = (AWS_DIR / "templates" / "types" / "cloud-mcu.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("CloudRigRuntimeFunction:", template)
        self.assertIn("CloudMcuRuntimeFunction:", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("AWS::Events::Rule", template)
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
        self.assertIn("Handler: rust.handler", template)
        self.assertIn("Architectures:", template)
        self.assertIn("- arm64", template)
        self.assertIn("RetentionInDays: 14", template)
        self.assertIn("CpuArchitecture: ARM64", template)
        self.assertIn("public.ecr.aws/docker/library/alpine:3.20", template)
        self.assertIn(
            "FunctionName: txing-cloud-rig-lambda",
            template,
        )
        self.assertIn("FunctionName: txing-cloud-mcu-lambda", template)
        self.assertIn("S3Bucket: !Ref LambdaArtifactsBucketName", template)
        self.assertIn("S3Key: lambda/txing-cloud-rig-lambda/current/bootstrap.zip", template)
        self.assertIn("S3Key: lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", template)
        self.assertNotIn("ThingName:", template)
        self.assertNotIn("THING_NAME", template)
        self.assertNotIn("${ThingName}", template)
        self.assertNotIn("AWS::Serverless::Function", template)
        self.assertNotIn("AWS::DynamoDB::Table", template)
        self.assertNotIn("dynamodb:", template)

    def test_enlist_stack_defines_lambda_and_minimal_permissions(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        enlist_template = (AWS_DIR / "templates" / "enlist.yaml").read_text(encoding="utf-8")

        self.assertIn("EnlistLayer:", root_template)
        self.assertIn("TemplateURL: templates/enlist.yaml", root_template)
        self.assertIn("TxingEnlistFunction:", enlist_template)
        self.assertIn("FunctionName: txing-enlist-lambda", enlist_template)
        self.assertIn("LogGroupName: /aws/lambda/txing-enlist-lambda", enlist_template)
        self.assertIn("RetentionInDays: 14", enlist_template)
        self.assertIn("Runtime: provided.al2023", enlist_template)
        self.assertIn("Handler: rust.handler", enlist_template)
        self.assertIn("Architectures:", enlist_template)
        self.assertIn("- arm64", enlist_template)
        self.assertIn("LambdaArtifactsBucketName:", enlist_template)
        self.assertIn("S3Bucket: !Ref LambdaArtifactsBucketName", enlist_template)
        self.assertIn("S3Key: lambda/txing-enlist-lambda/current/bootstrap.zip", enlist_template)
        self.assertNotIn("enlist/target/lambda/txing-enlist-lambda/bootstrap.zip", enlist_template)
        self.assertIn("MemorySize: 128", enlist_template)
        self.assertIn("TxingDischargeThingsOnStackDelete:", enlist_template)
        self.assertNotIn("TxingDischargeThingsOnDelete:", enlist_template)
        self.assertIn("Type: Custom::TxingDischargeThings", enlist_template)
        self.assertIn("CleanupType: TxingDischargeThings", enlist_template)
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
        self.assertIn("EnlistBoardVideoChannels", enlist_template)

    def test_rig_runtime_can_connect_with_managed_device_client_ids(self) -> None:
        template = _template_text()

        self.assertIn("Sid: RigMqttConnect", template)
        self.assertIn("client/*", template)
        self.assertIn("thing connectivity", template)

    def test_global_resources_use_cloudformation_generated_names(self) -> None:
        template = _template_text()

        self.assertIn("Type: AWS::IAM::Role", template)
        self.assertIn("Type: AWS::IAM::ManagedPolicy", template)
        self.assertIn("Type: AWS::IoT::RoleAlias", template)
        self.assertIn("Type: AWS::IoT::Policy", template)
        self.assertNotIn("\n      RoleName:", template)
        self.assertNotIn("\n      ManagedPolicyName:", template)
        self.assertNotIn("\n      RoleAlias:", template)
        self.assertNotIn("PolicyName: town-rig-device-policy", template)
        self.assertNotIn("PolicyName: !Sub ${AWS::StackName}-web-admin-iot-policy", template)

    def test_root_template_uses_nested_stacks(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")

        self.assertIn("Type: AWS::CloudFormation::Stack", root_template)
        self.assertIn("TemplateURL: templates/base.yaml", root_template)

    def test_cloud_mcu_runtime_uses_release_lambda_assets(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        cloud_mcu_template = (AWS_DIR / "templates" / "types" / "cloud-mcu.yaml").read_text(
            encoding="utf-8"
        )
        aws_justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        root_justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        project_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        self.assertRegex(project_version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertIn("_project-version-env:", root_justfile)
        self.assertIn("export_line TXING_VERSION_BASE", root_justfile)
        self.assertIn("export_line TXING_VERSION", root_justfile)
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
        self.assertIn("CognitoDomainPrefix: !Ref StackCognitoDomainPrefix", root_template)
        self.assertIn("AdminEmail: !Ref StackAdminEmail", root_template)
        self.assertIn("WebAppUrl: !Ref StackWebAppUrl", root_template)
        self.assertIn("TemplateURL: templates/types/cloud-mcu.yaml", root_template)
        self.assertIn("Runtime: provided.al2023", cloud_mcu_template)
        self.assertIn("Handler: rust.handler", cloud_mcu_template)
        self.assertIn("- arm64", cloud_mcu_template)
        self.assertIn("lambda/txing-cloud-rig-lambda/current/bootstrap.zip", cloud_mcu_template)
        self.assertIn("lambda/txing-cloud-mcu-lambda/current/bootstrap.zip", cloud_mcu_template)
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
        self.assertIn('Default: https://office.txing.dev', template)
        self.assertIn('- !Sub "${WebAppUrl}/"', template)
        self.assertIn("- https://txing.dev/", template)

    def test_static_manifests_use_plain_semver_only(self) -> None:
        manifest_paths = [
            REPO_ROOT / "shared" / "aws" / "python" / "pyproject.toml",
            REPO_ROOT / "shared" / "aws" / "enlist" / "Cargo.toml",
            REPO_ROOT / "devices" / "cloud-mcu" / "lambda" / "Cargo.toml",
            REPO_ROOT / "witness" / "Cargo.toml",
            REPO_ROOT / "devices" / "unit" / "board" / "pyproject.toml",
            REPO_ROOT / "rig" / "capability-protocol" / "Cargo.toml",
            REPO_ROOT / "rig" / "sparkplug-manager" / "Cargo.toml",
            REPO_ROOT / "rig" / "ble-connectivity" / "Cargo.toml",
            REPO_ROOT / "rig" / "aws-connectivity" / "Cargo.toml",
            REPO_ROOT / "office" / "package.json",
        ]
        for path in manifest_paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("+g", text, path)
            self.assertNotIn(".dirty", text, path)

    def test_aws_recipes_are_stateless_and_staged(self) -> None:
        checked_paths = [
            REPO_ROOT / "justfile",
            AWS_DIR / "justfile",
            AWS_DIR / "scripts" / "aws_lib.sh",
            REPO_ROOT / "devices" / "cloud-mcu" / "justfile",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

        self.assertIn("deploy-init parameter_file", text)
        self.assertIn("aws ssm put-parameter", text)
        self.assertIn("deploy_init_parameter_name()", text)
        self.assertIn("/txing/stack", text)
        self.assertIn("deploy stack_name=stack_name", text)
        self.assertIn(
            'parameter_overrides+=(--parameter-overrides "LambdaArtifactsBucketName=$artifact_bucket")',
            text,
        )
        self.assertNotIn("deploy CognitoDomainPrefix", text)
        self.assertNotIn("aws ssm get-parameter", text)
        self.assertIn("deploy-town town_name", text)
        self.assertIn("deploy-rig town_id", text)
        self.assertIn("deploy-device rig_id", text)
        self.assertIn("enlist payload_file", text)
        self.assertIn("discharge thing_id", text)
        self.assertIn("delete stack_name", text)
        self.assertIn("aws lambda invoke", text)
        self.assertIn("aws cloudformation delete-stack", text)
        self.assertIn("stack-delete-complete", text)
        self.assertIn("EnlistFunctionName", text)
        self.assertIn("stack_output()", text)
        self.assertIn("resolve_town_thing_name()", text)
        self.assertIn("resolve_rig_thing_name()", text)
        self.assertIn("resolve_device_thing_name()", text)
        self.assertIn("assume_stack_role()", text)
        self.assertIn("delete-packaging-buckets stack_name", text)
        self.assertIn("delete_s3_bucket_if_exists", text)
        self.assertNotIn("@deploy-lambda", text)
        self.assertNotIn(".state", text)
        self.assertNotIn("local_state_dir", text)
        self.assertNotIn("packaged_template_file", text)
        self.assertNotIn("config/rig.env", text)
        self.assertNotIn("config/board.env", text)
        self.assertNotIn("python -m aws.type_catalog \\\n      --region \"$AWS_REGION\" \\\n      sync", text)
        self.assertNotIn("python -m aws.device_registry", text)
        self.assertNotIn("ensure-town", text)
        self.assertNotIn("ensure-rig", text)
        self.assertNotIn("ensure-device", text)

    def test_cert_recipe_is_parameterless_and_writes_ignored_config_certs(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("cert rig_id='':", justfile)
        self.assertIn("greengrass-config rig_id='':", justfile)
        self.assertIn('effective_thing_name="$TXING_RIG_ID"', justfile)
        self.assertIn('cert_dir="{{project_root}}/config/certs/rig"', justfile)
        self.assertIn('root_ca_path="$cert_dir/AmazonRootCA1.pem"', justfile)
        self.assertIn('greengrass_config_path="$cert_dir/greengrass-lite.yaml"', justfile)
        self.assertIn("--endpoint-type iot:CredentialProvider", justfile)
        self.assertIn("--endpoint-type iot:Data-ATS", justfile)
        self.assertIn("GreengrassTokenExchangeRoleAlias", justfile)
        self.assertIn('privateKeyPath: "/var/lib/greengrass/credentials/rig.private.key"', justfile)
        self.assertIn('certificateFilePath: "/var/lib/greengrass/credentials/rig.cert.pem"', justfile)
        self.assertIn("greengrassConfig", justfile)
        self.assertIn("Rig certificate material is missing under $cert_dir", justfile)
        self.assertIn("https://www.amazontrust.com/repository/AmazonRootCA1.pem", justfile)
        self.assertIn("rootCaFile", justfile)
        self.assertIn("Certificate material already exists", justfile)
        self.assertIn("/config/certs/", gitignore)
        self.assertNotIn("@cert thing_name", justfile)
        self.assertNotIn("output_dir", justfile)

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
