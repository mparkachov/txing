from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]


class AgentDeployTests(unittest.TestCase):
    def deploy(self, unreserved: str, statuses: tuple[str, ...] = ()):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            requests = scratch / "requests.jsonl"
            aws = scratch / "aws"
            aws.write_text(textwrap.dedent('''\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import jmespath

                args = sys.argv[1:]
                with open(os.environ["DEPLOY_TEST_REQUESTS"], "a") as log:
                    log.write(json.dumps(args) + "\\n")
                if args[:2] == ["lambda", "get-account-settings"]:
                    print(os.environ["DEPLOY_TEST_UNRESERVED"])
                elif args[:2] == ["cloudformation", "list-stacks"]:
                    records = [{"StackName": "test-agent", "StackStatus": status}
                               for status in json.loads(os.environ["DEPLOY_TEST_STATUSES"])]
                    query = args[args.index("--query") + 1]
                    print(json.dumps(jmespath.search(query, {"StackSummaries": records})))
                elif args[:2] == ["cloudformation", "deploy"]:
                    print("mock deployment")
                else:
                    sys.exit("unexpected AWS call: " + repr(args))
                '''), encoding="utf-8")
            aws.chmod(0o755)
            just = scratch / "just"
            just.write_text("#!/bin/sh\nprintf '%s\\n' 'export TXING_AWS_STACK=test'\n", encoding="utf-8")
            just.chmod(0o755)
            recipe = (REPO_ROOT / "agent/justfile").read_text(encoding="utf-8")
            recipe = textwrap.dedent(recipe.split("\ndeploy:\n", 1)[1].split("\n@default:", 1)[0])
            recipe = recipe.replace("{{project_root}}", str(REPO_ROOT)).replace("{{agent_dir}}", str(REPO_ROOT / "agent"))
            result = subprocess.run(
                ["sh", "-eu", "-c", recipe],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PATH": f"{scratch}{os.pathsep}{os.environ['PATH']}",
                    "DEPLOY_TEST_REQUESTS": str(requests),
                    "DEPLOY_TEST_UNRESERVED": unreserved,
                    "DEPLOY_TEST_STATUSES": json.dumps(statuses),
                    "TXING_AGENT_CONTROLLER_BUCKET": "test-artifacts",
                    "TXING_AGENT_CONTROLLER_KEY": "reviewed/controller.zip",
                },
                timeout=10,
            )
            calls = [json.loads(line) for line in requests.read_text().splitlines()]
            return result, calls

    def test_insufficient_quota_stops_before_creating_resources(self):
        result, calls = self.deploy("10")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quota increase", result.stderr)
        self.assertEqual([call[:2] for call in calls], [["lambda", "get-account-settings"]])

    def test_unverifiable_quota_stops_before_creating_resources(self):
        result, calls = self.deploy("None")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_deleted_history_allows_disabled_redeployment(self):
        result, calls = self.deploy("1000", ("DELETE_COMPLETE",))
        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = calls[-1]
        self.assertEqual(deployment[:2], ["cloudformation", "deploy"])
        self.assertIn("AutomationEnabled=false", deployment)
        self.assertIn("PrerequisitesConfirmed=false", deployment)

    def test_failed_stack_requires_explicit_manual_deletion(self):
        result, calls = self.deploy("1000", ("DELETE_COMPLETE", "ROLLBACK_COMPLETE"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deleted manually", result.stderr)
        self.assertNotIn(["cloudformation", "deploy"], [call[:2] for call in calls])


if __name__ == "__main__":
    unittest.main()
