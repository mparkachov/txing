"""Lifecycle activation and serialization gates; no AWS calls."""
import pathlib
import unittest

import yaml


class Loader(yaml.SafeLoader):
    pass


def tagged(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag if tag in ("Ref", "Condition") else f"Fn::{tag}": value}


Loader.add_multi_constructor("!", tagged)
TEMPLATE = yaml.load(
    (pathlib.Path(__file__).parents[1] / "template.yaml").read_text(), Loader=Loader
)


def evaluate(value, parameters):
    if not isinstance(value, dict):
        return value
    name, argument = next(iter(value.items()))
    if name == "Ref":
        return parameters[argument]
    if name == "Condition":
        return evaluate(TEMPLATE["Conditions"][argument], parameters)
    if name == "Fn::Equals":
        return evaluate(argument[0], parameters) == evaluate(argument[1], parameters)
    if name == "Fn::Not":
        return not evaluate(argument[0], parameters)
    if name == "Fn::And":
        return all(evaluate(item, parameters) for item in argument)
    if name == "Fn::If":
        condition = evaluate({"Condition": argument[0]}, parameters)
        return evaluate(argument[1 if condition else 2], parameters)
    raise AssertionError(f"Unexpected condition: {name}")


class LifecycleTemplateTests(unittest.TestCase):
    def parameters(self, image="", controller="", enabled="false"):
        return {
            "CompanionImageDigest": image,
            "ControllerLambdaS3Key": controller,
            "EnableLifecycle": enabled,
        }

    def test_activation_requires_both_artifacts(self):
        rule = TEMPLATE["Rules"]["LifecycleRequiresArtifacts"]
        for image, controller in (("", ""), ("digest", ""), ("", "versioned.zip")):
            params = self.parameters(image, controller, "true")
            self.assertTrue(evaluate(rule["RuleCondition"], params))
            self.assertFalse(evaluate(rule["Assertions"][0]["Assert"], params))
            self.assertFalse(evaluate({"Condition": "LifecycleEnabled"}, params))
        self.assertTrue(evaluate(rule["Assertions"][0]["Assert"], self.parameters("digest", "versioned.zip", "true")))

    def test_default_off_and_explicit_on(self):
        self.assertEqual(TEMPLATE["Parameters"]["EnableLifecycle"]["Default"], "false")
        resources = TEMPLATE["Resources"]
        for enabled, disabled, state in (("false", True, "DISABLED"), ("true", False, "ENABLED")):
            params = self.parameters("digest", "versioned.zip", enabled)
            self.assertEqual(evaluate(resources["CompanionSparkplugRule"]["Properties"]["TopicRulePayload"]["RuleDisabled"], params), disabled)
            self.assertEqual(evaluate(resources["CompanionMinuteRule"]["Properties"]["State"], params), state)
        for name in ("CompanionControllerFunction", "CompanionSparkplugRule", "CompanionMinuteRule"):
            self.assertEqual(resources[name]["Condition"], "HasRunnableController")

    def test_serialization_completed_shadow_and_bounded_delivery(self):
        resources = TEMPLATE["Resources"]
        self.assertEqual(resources["CompanionControllerFunction"]["Properties"]["ReservedConcurrentExecutions"], 1)
        sql = resources["CompanionSparkplugRule"]["Properties"]["TopicRulePayload"]["Sql"]
        self.assertIn("/shadow/name/sparkplug/update/documents", sql)
        self.assertIn("topic(3) AS thingName", sql)
        minute = resources["CompanionMinuteRule"]["Properties"]
        self.assertEqual(minute["ScheduleExpression"], "rate(1 minute)")
        self.assertEqual(minute["Targets"][0]["Input"], '{"kind":"sweep"}')
        self.assertEqual(minute["Targets"][0]["RetryPolicy"]["MaximumRetryAttempts"], 0)
        async_config = resources["CompanionControllerAsyncConfig"]["Properties"]
        self.assertEqual(async_config["MaximumRetryAttempts"], 0)
        self.assertEqual(async_config["MaximumEventAgeInSeconds"], 60)
        for name in ("CompanionSparkplugInvokePermission", "CompanionMinuteInvokePermission"):
            self.assertIn("SourceArn", resources[name]["Properties"])
            self.assertIn("SourceAccount", resources[name]["Properties"])

    def test_no_idle_task_service_and_only_assigned_controller_invocation(self):
        resources = TEMPLATE["Resources"]
        self.assertFalse(any(resource["Type"] == "AWS::ECS::Service" for resource in resources.values()))
        statements = resources["CompanionTaskRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        invoke = next(statement for statement in statements if statement["Sid"] == "ReportReadinessToController")
        self.assertEqual(invoke["Action"], "lambda:InvokeFunction")
        self.assertEqual(invoke["Resource"], {"Fn::Sub": "arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:${EnvironmentStackName}-tbot-companion"})


if __name__ == "__main__":
    unittest.main()
