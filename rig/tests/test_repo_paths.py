from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rig.repo_paths import _discover_repo_root


class RepoPathDetectionTests(unittest.TestCase):
    def test_repo_root_detection_uses_rig_working_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            rig_dir = repo_root / "rig"
            docs_dir = repo_root / "docs"
            rig_dir.mkdir()
            docs_dir.mkdir()
            (rig_dir / "pyproject.toml").write_text("", encoding="utf-8")
            (docs_dir / "txing-shadow.schema.json").write_text("{}", encoding="utf-8")

            installed_module = (
                rig_dir
                / ".venv"
                / "lib"
                / "python3.13"
                / "site-packages"
                / "rig"
                / "repo_paths.py"
            )
            installed_module.parent.mkdir(parents=True)
            installed_module.write_text("", encoding="utf-8")

            detected = _discover_repo_root(
                cwd=rig_dir,
                module_file=installed_module,
                env_repo_root=None,
            )

        self.assertEqual(detected, repo_root.resolve())


if __name__ == "__main__":
    unittest.main()
