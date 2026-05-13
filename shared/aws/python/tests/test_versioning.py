from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release_version.py"


def _load_release_module():
    spec = importlib.util.spec_from_file_location("txing_release_version", RELEASE_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReleaseVersionTests(unittest.TestCase):
    def test_release_script_bumps_patch_by_non_bot_commit_count(self) -> None:
        release_version = _load_release_module()
        event = {
            "commits": [
                {"message": "feat: first", "author": {"username": "maxim"}},
                {"message": "fix: second", "author": {"username": "maxim"}},
                {
                    "message": "chore: release v0.8.3 [skip ci]",
                    "author": {"username": "github-actions[bot]"},
                },
            ]
        }

        self.assertEqual(release_version.plan_release("0.8.1", event)["next_version"], "0.8.3")
        self.assertEqual(release_version.plan_release("0.8.1", event)["commit_count"], "2")

    def test_release_script_ignores_bot_only_push(self) -> None:
        release_version = _load_release_module()
        event = {
            "commits": [
                {
                    "message": "chore: release v0.8.2 [skip ci]",
                    "committer": {
                        "email": "41898282+github-actions[bot]@users.noreply.github.com"
                    },
                }
            ]
        }

        self.assertEqual(
            release_version.plan_release("0.8.1", event),
            {
                "should_release": "false",
                "current_version": "0.8.1",
                "next_version": "0.8.1",
                "tag": "v0.8.1",
                "commit_count": "0",
            },
        )

    def test_release_script_cli_writes_version_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            event_path = repo / "event.json"
            outputs_path = repo / "outputs.txt"
            (repo / "VERSION").write_text("0.8.1\n", encoding="utf-8")
            event_path.write_text(
                json.dumps({"commits": [{"message": "feat: release me"}]}),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    "python3",
                    str(RELEASE_SCRIPT),
                    "--repo",
                    str(repo),
                    "--event",
                    str(event_path),
                    "--write",
                    "--outputs",
                    str(outputs_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )

            self.assertEqual((repo / "VERSION").read_text(encoding="utf-8"), "0.8.2\n")
            self.assertIn("next_version=0.8.2", outputs_path.read_text(encoding="utf-8"))
            self.assertIn("tag=v0.8.2", outputs_path.read_text(encoding="utf-8"))


class VersionEnvironmentTests(unittest.TestCase):
    def test_project_version_env_uses_plain_version_and_reports_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            root_justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
            version_recipe = root_justfile.split("\n[private]\n_project-aws-env", 1)[0]
            (repo / "justfile").write_text(version_recipe, encoding="utf-8")
            (repo / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "add", "VERSION", "justfile"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
            )

            clean = subprocess.run(
                ["just", "--justfile", str(repo / "justfile"), "_project-version-env"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertIn("export TXING_VERSION=1.2.3", clean)
            self.assertIn("export TXING_GIT_DIRTY=false", clean)

            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(
                ["just", "--justfile", str(repo / "justfile"), "_project-version-env"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertIn("export TXING_VERSION=1.2.3", dirty)
            self.assertIn("export TXING_GIT_DIRTY=true", dirty)
            self.assertNotIn("+g", dirty)

    def test_rig_deploy_defaults_to_plain_semver_and_immutable_artifacts(self) -> None:
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")

        self.assertIn("deploy target='auto'", rig_justfile)
        self.assertIn('env_scope="rig"', rig_justfile)
        self.assertIn('deploy_target="$RIG_TYPE"', rig_justfile)
        self.assertIn("TXING_ALLOW_DIRTY_DEPLOY", rig_justfile)
        self.assertIn("Refusing production Greengrass deploy from a dirty worktree.", rig_justfile)
        self.assertIn("^[0-9]+\\.[0-9]+\\.[0-9]+$", rig_justfile)
        self.assertIn('local key="artifacts/$component/$resolved_component_version/$filename"', rig_justfile)
        self.assertIn("aws s3api head-object", rig_justfile)
        self.assertNotIn("artifact_version_path", rig_justfile)

    def test_release_workflow_commits_version_and_tag(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "release-version.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("on:", workflow)
        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("scripts/release_version.py", workflow)
        self.assertIn("chore: release v${{ steps.release.outputs.next_version }} [skip ci]", workflow)
        self.assertIn('git tag "v${{ steps.release.outputs.next_version }}"', workflow)


if __name__ == "__main__":
    unittest.main()
