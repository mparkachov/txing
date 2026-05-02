from __future__ import annotations

from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


def _template_text() -> str:
    template_paths = [AWS_DIR / "template.yaml"]
    template_paths.extend(sorted((AWS_DIR / "templates").glob("*.yaml")))
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

    def test_rig_time_service_topics_are_authorized(self) -> None:
        template = _template_text()

        self.assertIn("Sid: RigTimeServiceTopics", template)
        self.assertIn("Sid: RigTimeServiceTopicFilters", template)
        self.assertIn("topic/txings/*/time/command", template)
        self.assertIn("topic/txings/*/time/state", template)
        self.assertIn("topic/txings/*/time/command-result", template)
        self.assertIn("topicfilter/txings/*/time/state", template)
        self.assertIn("topicfilter/txings/*/time/command-result", template)

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
        self.assertIn("sparkplug-witness", template)
        self.assertIn("iot:GetThingShadow", template)

    def test_template_uses_dynamic_txing_log_group_prefix_for_rig_logs(self) -> None:
        template = _template_text()

        self.assertNotIn("LogGroupName: /town/rig/txing", template)
        self.assertIn("logs:CreateLogGroup", template)
        self.assertIn("logs:PutRetentionPolicy", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn("iot:ListThings", template)
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
        self.assertIn("greengrass:*", template)
        self.assertIn("TxingGreengrassArtifactsBucket:", template)
        self.assertIn("Sid: RigGreengrassArtifactObjectRead", template)
        self.assertIn("GreengrassTokenExchangeRoleAliasArn:", template)
        self.assertIn("GreengrassArtifactsBucketName:", template)

    def test_base_stack_cleans_disposable_buckets_on_delete(self) -> None:
        template = _template_text()

        self.assertIn("TxingStackCleanupFunction:", template)
        self.assertIn("Type: Custom::TxingS3BucketCleanup", template)
        self.assertIn("TxingGreengrassArtifactsBucketCleanup:", template)
        self.assertIn("TxingWebBucketCleanup:", template)
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

    def test_aws_recipes_are_stateless_and_staged(self) -> None:
        checked_paths = [
            REPO_ROOT / "justfile",
            AWS_DIR / "justfile",
            AWS_DIR / "scripts" / "aws_lib.sh",
            REPO_ROOT / "devices" / "time" / "justfile",
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

        self.assertIn("@deploy", text)
        self.assertIn("@town-deploy", text)
        self.assertIn("@rig-deploy", text)
        self.assertIn("@device-deploy", text)
        self.assertIn("stack_output()", text)
        self.assertIn("resolve_town_thing_name()", text)
        self.assertIn("resolve_rig_thing_name()", text)
        self.assertIn("resolve_device_thing_name()", text)
        self.assertIn("assume_stack_role()", text)
        self.assertIn("@delete-packaging-buckets", text)
        self.assertIn("delete_s3_bucket_if_exists", text)
        self.assertIn("legacy_time_lambda_artifact_bucket_name", text)
        self.assertIn('resolved_artifact_bucket="$(ensure_artifact_bucket)"', text)
        self.assertNotIn('resolved_artifact_bucket="txing-time-lambda-${account_id}-${region}"', text)
        self.assertNotIn(".state", text)
        self.assertNotIn("local_state_dir", text)
        self.assertNotIn("packaged_template_file", text)
        self.assertNotIn("config/aws.config", text)
        self.assertNotIn("aws_config_file", text)
        self.assertNotIn("config/rig.env", text)
        self.assertNotIn("config/board.env", text)

    def test_cert_recipe_is_parameterless_and_writes_ignored_config_certs(self) -> None:
        justfile = (AWS_DIR / "justfile").read_text(encoding="utf-8")
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("@cert rig_id='':", justfile)
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
        justfile = (AWS_DIR / "scripts" / "aws_lib.sh").read_text(encoding="utf-8")

        self.assertIn('"thingConnectivityIndexingMode":"STATUS"', justfile)
        self.assertIn('[ "$thing_connectivity_indexing_mode" = "STATUS" ]', justfile)
        self.assertNotIn('"thingConnectivityIndexingMode":"OFF"', justfile)
        self.assertNotIn("REGISTRY/OFF", justfile)


if __name__ == "__main__":
    unittest.main()
