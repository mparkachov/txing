from __future__ import annotations

from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


def _template_text() -> str:
    template_paths = [AWS_DIR / "template.yaml"]
    template_paths.extend(sorted((AWS_DIR / "templates").glob("*.yaml")))
    template_paths.extend(sorted((AWS_DIR / "templates" / "types").glob("*.yaml")))
    return "\n".join(path.read_text(encoding="utf-8") for path in template_paths)


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
        self.assertIn("Code: ../../../witness/target/lambda/txing-witness-lambda/bootstrap.zip", template)
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
            "CloudTimeTypeCatalog",
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
            "templates/types/cloud-time.yaml",
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
        self.assertIn("ThingTypeName: time", template)
        self.assertIn("TimeRuntimeFunction:", template)
        self.assertIn("TimeRuntimeMcpTopicRule:", template)
        self.assertIn("FunctionName: txing-time-lambda", template)
        self.assertIn("Code: ../../../../devices/time/lambda/target/lambda/txing-time-lambda/bootstrap.zip", template)
        self.assertIn("CatalogBasePath: /txing/town/cloud/time", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/unit", template)
        self.assertIn("CatalogBasePath: /txing/town/raspi/power", template)
        self.assertIn("kind: deviceType", template)
        self.assertIn("EnlistFunctionName:", root_template)
        self.assertIn("EnlistFunctionArn:", root_template)
        self.assertIn("RigTypeCatalogRead", template)
        self.assertIn("ssm:GetParametersByPath", template)

    def test_cloud_time_template_defines_rust_lambda_schedule_state_and_mcp_rules(self) -> None:
        template = (AWS_DIR / "templates" / "types" / "cloud-time.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("TimeRuntimeFunction:", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("AWS::Events::Rule", template)
        self.assertIn("AWS::IoT::TopicRule", template)
        self.assertIn("rate(1 minute)", template)
        self.assertIn("txings/+/mcp/session/+/c2s", template)
        self.assertIn("txings/+/capability/v2/command", template)
        self.assertIn("TimeRuntimeCommandTopicRule:", template)
        self.assertIn("TimeRuntimeCommandRulePermission:", template)
        self.assertIn("iot:GetRetainedMessage", template)
        self.assertIn("iot:GetThingShadow", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn("TimeRuntimeVersion:", template)
        self.assertIn("SERVER_VERSION: !Ref TimeRuntimeVersion", template)
        self.assertIn("topic/txings/*/capability/v2/*", template)
        self.assertIn("topic/txings/*/mcp/*", template)
        self.assertIn("Runtime: provided.al2023", template)
        self.assertIn("Handler: rust.handler", template)
        self.assertIn("Architectures:", template)
        self.assertIn("- arm64", template)
        self.assertIn("RetentionInDays: 14", template)
        self.assertIn(
            "FunctionName: txing-time-lambda",
            template,
        )
        self.assertIn(
            "Code: ../../../../devices/time/lambda/target/lambda/txing-time-lambda/bootstrap.zip",
            template,
        )
        self.assertNotIn("ThingName:", template)
        self.assertNotIn("THING_NAME", template)
        self.assertNotIn("${ThingName}", template)
        self.assertNotIn("txing-time-${ThingName}", template)
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
        self.assertIn(
            "Code: ../enlist/target/lambda/txing-enlist-lambda/bootstrap.zip",
            enlist_template,
        )
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
            "ssm:GetParametersByPath",
        ):
            self.assertIn(action, enlist_template)
        self.assertNotIn("kinesisvideo:", enlist_template)
        self.assertNotIn("EnlistBoardVideoChannels", enlist_template)

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

    def test_global_version_is_parameterized_through_root_and_time_runtime(self) -> None:
        root_template = (AWS_DIR / "template.yaml").read_text(encoding="utf-8")
        cloud_time_template = (AWS_DIR / "templates" / "types" / "cloud-time.yaml").read_text(
            encoding="utf-8"
        )
        aws_justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        root_justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

        self.assertRegex(
            (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            r"^[0-9]+\.[0-9]+\.[0-9]+$",
        )
        self.assertIn("_project-version-env:", root_justfile)
        self.assertIn("export_line TXING_VERSION_BASE", root_justfile)
        self.assertIn("export_line TXING_VERSION", root_justfile)
        self.assertIn("TxingVersion:", root_template)
        self.assertIn("WebAppUrl:", root_template)
        self.assertIn("WebAppUrl: !Ref WebAppUrl", root_template)
        self.assertIn("TimeRuntimeVersion: !Ref TxingVersion", root_template)
        self.assertIn("Value: !Ref TxingVersion", root_template)
        self.assertIn("TimeRuntimeVersion:", cloud_time_template)
        self.assertIn("SERVER_VERSION: !Ref TimeRuntimeVersion", cloud_time_template)
        self.assertIn("Runtime: provided.al2023", cloud_time_template)
        self.assertIn("Handler: rust.handler", cloud_time_template)
        self.assertIn("- arm64", cloud_time_template)
        self.assertNotIn('SERVER_VERSION: "0.5.0"', cloud_time_template)
        self.assertIn('"TxingVersion=$TXING_VERSION"', aws_justfile)
        self.assertIn('"WebAppUrl=$web_app_url"', aws_justfile)

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
        self.assertIn('Default: https://office.txing.dev', root_template)
        self.assertIn('- !Sub "${WebAppUrl}/"', template)

    def test_static_manifests_use_plain_semver_only(self) -> None:
        manifest_paths = [
            REPO_ROOT / "shared" / "aws" / "python" / "pyproject.toml",
            REPO_ROOT / "shared" / "aws" / "enlist" / "Cargo.toml",
            REPO_ROOT / "devices" / "time" / "lambda" / "Cargo.toml",
            REPO_ROOT / "witness" / "Cargo.toml",
            REPO_ROOT / "devices" / "unit" / "rig" / "python" / "pyproject.toml",
            REPO_ROOT / "devices" / "unit" / "board" / "pyproject.toml",
            REPO_ROOT / "rig" / "capability-protocol" / "Cargo.toml",
            REPO_ROOT / "rig" / "sparkplug-manager" / "Cargo.toml",
            REPO_ROOT / "rig" / "ble-connectivity" / "Cargo.toml",
            REPO_ROOT / "rig" / "aws-connectivity" / "Cargo.toml",
            REPO_ROOT / "web" / "package.json",
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
            REPO_ROOT / "devices" / "time" / "justfile",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

        self.assertIn("deploy CognitoDomainPrefix", text)
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
        self.assertIn("delete-packaging-buckets include_legacy_time_lambda", text)
        self.assertIn("delete_s3_bucket_if_exists", text)
        self.assertIn("legacy_time_lambda_artifact_bucket_name", text)
        self.assertNotIn("@deploy-lambda", text)
        self.assertNotIn("time::deploy-lambda", text)
        self.assertNotIn('resolved_artifact_bucket="txing-time-lambda-${account_id}-${region}"', text)
        self.assertNotIn(".state", text)
        self.assertNotIn("local_state_dir", text)
        self.assertNotIn("packaged_template_file", text)
        self.assertNotIn("config/aws.config", text)
        self.assertNotIn("aws_config_file", text)
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
        self.assertIn('effective_thing_name="$TXING_RIG_ID"', justfile)
        self.assertIn('cert_dir="{{project_root}}/config/certs/rig"', justfile)
        self.assertIn('root_ca_path="$cert_dir/AmazonRootCA1.pem"', justfile)
        self.assertIn("https://www.amazontrust.com/repository/AmazonRootCA1.pem", justfile)
        self.assertIn("rootCaFile", justfile)
        self.assertIn("Certificate material already exists", justfile)
        self.assertIn("/config/certs/", gitignore)
        self.assertNotIn("@cert thing_name", justfile)
        self.assertNotIn("output_dir", justfile)

    def test_aws_justfile_enables_thing_connectivity_indexing(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        deploy_recipe = justfile.split("deploy ", 1)[1].split("\n\n", 1)[0]
        configure_recipe = justfile.split("configure-indexing ", 1)[1].split("\n\n", 1)[0]
        aws_lib = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")

        self.assertNotIn("configure_indexing_and_wait", deploy_recipe)
        self.assertIn("configure-indexing region=region profile=profile", justfile)
        self.assertIn("configure_indexing_and_wait", configure_recipe)
        self.assertIn('"thingConnectivityIndexingMode":"STATUS"', aws_lib)
        self.assertIn('[ "$thing_connectivity_indexing_mode" = "STATUS" ]', aws_lib)
        self.assertNotIn('"thingConnectivityIndexingMode":"OFF"', aws_lib)
        self.assertNotIn("REGISTRY/OFF", aws_lib)


if __name__ == "__main__":
    unittest.main()
