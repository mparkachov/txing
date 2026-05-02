from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[5]
TEMPLATE = REPO_ROOT / "shared" / "aws" / "templates" / "types" / "cloud-time.yaml"


class TimeDeviceTemplateTests(unittest.TestCase):
    def test_template_declares_lambda_schedule_state_and_mcp_topic_rule(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("TimeRuntimeFunction:", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("AWS::Events::Rule", template)
        self.assertIn("AWS::IoT::TopicRule", template)
        self.assertIn("rate(1 minute)", template)
        self.assertIn("txings/+/mcp/session/+/c2s", template)
        self.assertIn("iot:GetRetainedMessage", template)
        self.assertIn("iot:GetThingShadow", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn("TimeRuntimeVersion:", template)
        self.assertIn("SERVER_VERSION: !Ref TimeRuntimeVersion", template)
        self.assertIn("topic/txings/*/time/*", template)
        self.assertIn("topic/txings/*/mcp/*", template)
        self.assertIn("Code: ../../../../devices/time/lambda/python/src", template)
        self.assertNotIn("ThingName:", template)
        self.assertNotIn("THING_NAME", template)
        self.assertNotIn("${ThingName}", template)
        self.assertNotIn("txing-time-${ThingName}", template)
        self.assertNotIn("AWS::Serverless::Function", template)
        self.assertNotIn("AWS::DynamoDB::Table", template)
        self.assertNotIn("dynamodb:", template)


if __name__ == "__main__":
    unittest.main()
