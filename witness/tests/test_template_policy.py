from __future__ import annotations

from pathlib import Path
import unittest


class WitnessTemplatePolicyTests(unittest.TestCase):
    def test_template_defines_sparkplug_witness_projection(self) -> None:
        template = (
            Path(__file__).resolve().parents[1] / "template.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("TxingSparkplugWitnessFunction", template)
        self.assertIn("AWS::Lambda::Function", template)
        self.assertIn("TxingSparkplugWitnessTopicRule", template)
        self.assertIn("TxingSparkplugWitnessInvokePermission", template)
        self.assertIn("RuleName: !Sub ${AWS::StackName}-sparkplug-witness", template)
        self.assertIn(
            "SourceArn: !Sub arn:${AWS::Partition}:iot:${AWS::Region}:${AWS::AccountId}:rule/${AWS::StackName}-sparkplug-witness",
            template,
        )
        self.assertIn("encode(*, 'base64')", template)
        self.assertIn("iot:SearchIndex", template)
        self.assertIn("iot:UpdateThingShadow", template)
        self.assertIn("iot:DescribeEndpoint", template)


if __name__ == "__main__":
    unittest.main()
