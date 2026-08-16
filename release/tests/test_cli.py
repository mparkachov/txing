from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from txing_release import cli  # noqa: E402


class ReleaseCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_root = cli.ROOT

    def tearDown(self) -> None:
        cli.ROOT = self._old_root

    def _write(self, path: str, content: str) -> None:
        full_path = cli.ROOT / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def _write_minimal_repo(self, version: str = "1.2.3") -> None:
        for component in ("rig", "lambda", "unit", "cyberbrick", "kvs-master", "office"):
            self._write(f"release/versions/{component}", f"{version}\n")
        self._write(
            "shared/aws/python/pyproject.toml",
            '[project]\nname = "aws"\nversion = "0.0.0"\n',
        )
        self._write(
            "shared/aws/python/uv.lock",
            'version = 1\n\n[[package]]\nname = "aws"\nversion = "0.0.0"\n',
        )
        self._write(
            "office/package.json",
            json.dumps({"name": "office", "version": version}, indent=2) + "\n",
        )
        self._write(
            "office/src/config.ts",
            f"const fallback = '{version}'\nconst config = {{ txingVersion: '{version}' }}\n",
        )
        self._write(
            "office/vite.config.ts",
            f"const fallback = '{version}'\n",
        )

    def test_bump_updates_only_selected_component_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                cli.bump("unit", "1.2.4")

            self.assertEqual((cli.ROOT / "release/versions/unit").read_text(), "1.2.4\n")
            self.assertEqual((cli.ROOT / "release/versions/rig").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/lambda").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/office").read_text(), "1.2.3\n")
            self.assertEqual(
                (cli.ROOT / "release/versions/cyberbrick").read_text(), "1.2.3\n"
            )
            self.assertEqual(
                (cli.ROOT / "release/versions/kvs-master").read_text(), "1.2.3\n"
            )
            self.assertEqual(
                json.loads((cli.ROOT / "office/package.json").read_text())["version"],
                "1.2.3",
            )

    def test_cyberbrick_bump_updates_all_three_owned_version_surfaces_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                cli.bump("cyberbrick", "1.2.4")

            self.assertEqual(
                (cli.ROOT / "release/versions/cyberbrick").read_text(), "1.2.4\n"
            )
            self.assertEqual((cli.ROOT / "release/versions/unit").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/rig").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/lambda").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/office").read_text(), "1.2.3\n")
            self.assertEqual(
                (cli.ROOT / "release/versions/kvs-master").read_text(), "1.2.3\n"
            )

    def test_kvs_master_bump_updates_only_shared_release_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                cli.bump("kvs-master", "1.2.4")

            self.assertEqual(
                (cli.ROOT / "release/versions/kvs-master").read_text(), "1.2.4\n"
            )
            self.assertEqual((cli.ROOT / "release/versions/unit").read_text(), "1.2.3\n")
            self.assertEqual(
                (cli.ROOT / "release/versions/cyberbrick").read_text(), "1.2.3\n"
            )

    def test_lambda_bump_updates_only_runtime_lambda_release_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                cli.bump("lambda", "1.2.4")

            self.assertEqual((cli.ROOT / "release/versions/lambda").read_text(), "1.2.4\n")
            self.assertEqual(
                (cli.ROOT / "shared/aws/python/pyproject.toml").read_text(),
                '[project]\nname = "aws"\nversion = "0.0.0"\n',
            )
            self.assertEqual(
                (cli.ROOT / "shared/aws/python/uv.lock").read_text(),
                'version = 1\n\n[[package]]\nname = "aws"\nversion = "0.0.0"\n',
            )

    def test_office_bump_updates_component_package_and_runtime_fallback_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                cli.bump("office", "1.2.4")

            self.assertEqual((cli.ROOT / "release/versions/office").read_text(), "1.2.4\n")
            self.assertEqual(
                json.loads((cli.ROOT / "office/package.json").read_text())["version"],
                "1.2.4",
            )
            self.assertIn(
                "txingVersion: '1.2.4'",
                (cli.ROOT / "office/src/config.ts").read_text(),
            )
            self.assertEqual(
                (cli.ROOT / "office/vite.config.ts").read_text(),
                "const fallback = '1.2.3'\n",
            )

    def test_current_version_bump_audits_with_warnings_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()
            # office still mirrors its version into a source literal; the board
            # components inject theirs at build time and manage no source files.
            self._write("office/src/config.ts", "export const version = '1.2.2'\n")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                cli.bump("office", "1.2.3")

            self.assertIn("office managed version sources:", stdout.getvalue())
            self.assertEqual((cli.ROOT / "release/versions/office").read_text(), "1.2.3\n")

    def test_standalone_check_command_is_not_registered(self) -> None:
        argv = sys.argv
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            sys.argv = ["txing-release", "check"]
            with self.assertRaises(SystemExit) as raised:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    cli.main()
        finally:
            sys.argv = argv

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_print_command_lists_release_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cli.ROOT = Path(temp_dir)
            self._write_minimal_repo()
            self._write("release/versions/office", "4.5.6\n")

            argv = sys.argv
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                sys.argv = ["txing-release", "print"]
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    cli.main()
            finally:
                sys.argv = argv

            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(
                stdout.getvalue(),
                "rig: 1.2.3\nlambda: 1.2.3\nunit: 1.2.3\ncyberbrick: 1.2.3\n"
                "kvs-master: 1.2.3\noffice: 4.5.6\n",
            )


if __name__ == "__main__":
    unittest.main()
