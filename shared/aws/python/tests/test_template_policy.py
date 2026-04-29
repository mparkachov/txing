from __future__ import annotations

from pathlib import Path
import unittest


class AwsTemplatePolicyTests(unittest.TestCase):
    def test_rig_and_device_video_topics_are_authorized(self) -> None:
        template = (
            Path(__file__).resolve().parents[2] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("Sid: RigVideoDiscoveryTopics", template)
        self.assertIn("Sid: RigVideoDiscoveryTopicFilters", template)
        self.assertIn("topic/txings/*/video/descriptor", template)
        self.assertIn("topic/txings/*/video/status", template)
        self.assertIn("topicfilter/txings/*/video/descriptor", template)
        self.assertIn("topicfilter/txings/*/video/status", template)
        self.assertIn("Sid: DeviceVideoTopics", template)
        self.assertIn("iot:RetainPublish", template)

    def test_legacy_raw_cmd_vel_topic_permissions_are_removed(self) -> None:
        template = (
            Path(__file__).resolve().parents[2] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Sid: RigCmdVelTopics", template)
        self.assertNotIn("Sid: RigCmdVelTopicFilters", template)
        self.assertNotIn("Sid: DeviceCmdVelTopics", template)
        self.assertNotIn("Sid: DeviceCmdVelTopicFilters", template)
        self.assertNotIn("board/cmd_vel", template)

    def test_template_defines_sparkplug_witness_projection(self) -> None:
        template = (
            Path(__file__).resolve().parents[2] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("TxingSparkplugWitnessFunction", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("TxingSparkplugWitnessTopicRule", template)
        self.assertIn("TxingSparkplugWitnessInvokePermission", template)
        self.assertIn("encode(*, 'base64')", template)
        self.assertIn("iot:SearchIndex", template)

    def test_device_runtime_policy_allows_describe_thing(self) -> None:
        template = (
            Path(__file__).resolve().parents[2] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("Sid: DeviceDescribeThing", template)
        self.assertIn("Action: iot:DescribeThing", template)

    def test_device_runtime_policy_allows_sparkplug_command_subscribe(self) -> None:
        template = (
            Path(__file__).resolve().parents[2] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("Sid: DeviceSparkplugMqttTopics", template)
        self.assertIn("Sid: DeviceSparkplugMqttTopicFilters", template)
        self.assertIn("topic/spBv1.0/*", template)
        self.assertIn("topicfilter/spBv1.0/*", template)


if __name__ == "__main__":
    unittest.main()
