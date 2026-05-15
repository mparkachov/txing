from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest


AWS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AWS_DIR.parents[1]


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

    def test_rig_deploy_defaults_to_project_release_and_immutable_artifacts(self) -> None:
        rig_justfile = (REPO_ROOT / "rig" / "justfile").read_text(encoding="utf-8")

        self.assertIn("deploy target='auto'", rig_justfile)
        self.assertIn('env_scope="rig"', rig_justfile)
        self.assertIn('deploy_target="$RIG_TYPE"', rig_justfile)
        self.assertIn('resolved_component_version="$TXING_VERSION"', rig_justfile)
        self.assertIn("Refusing production Greengrass deploy from a dirty worktree.", rig_justfile)
        self.assertNotIn("TXING_ALLOW_DIRTY_DEPLOY", rig_justfile)
        self.assertNotIn("TXING_RIG_ALLOW_DIRTY_DEPLOY", rig_justfile)
        self.assertNotIn("_check-rig-cargo-version", rig_justfile)
        self.assertIn('local key="artifacts/$component/$resolved_component_version/$filename"', rig_justfile)
        self.assertIn("aws s3api head-object", rig_justfile)
        self.assertNotIn("artifact_version_path", rig_justfile)

    def test_release_version_is_manual(self) -> None:
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "release-version.yml").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "release_version.py").exists())


if __name__ == "__main__":
    unittest.main()
