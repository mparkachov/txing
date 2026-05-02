from __future__ import annotations

from pathlib import Path
import unittest


TEMPLATE = Path(__file__).resolve().parents[3] / "aws" / "template.yaml"


class TimeDeviceTemplateTests(unittest.TestCase):
    def test_template_declares_lambda_schedule_state_and_mcp_topic_rule(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("AWS::Serverless::Function", template)
        self.assertIn("AWS::Events::Rule", template)
        self.assertIn("AWS::IoT::TopicRule", template)
        self.assertIn("rate(1 minute)", template)
        self.assertIn("txings/${ThingName}/mcp/session/+/c2s", template)
        self.assertIn("iot:GetRetainedMessage", template)
        self.assertIn("iot:GetThingShadow", template)
        self.assertIn("thing/${ThingName}/time", template)
        self.assertIn("thing/${ThingName}/mcp", template)
        self.assertNotIn("AWS::DynamoDB::Table", template)
        self.assertNotIn("dynamodb:", template)


if __name__ == "__main__":
    unittest.main()
