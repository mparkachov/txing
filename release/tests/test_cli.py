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
        for component in ("rig", "lambda", "unit", "office"):
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
            "devices/unit/daemon/internal/daemon/version.go",
            f'package daemon\n\nconst packageVersion = "{version}"\n',
        )
        self._write(
            "devices/unit/board/kvs_master/include/kvs_master/version.hpp",
            f'inline constexpr std::string_view kTxingUnitKvsMasterVersion = "{version}";\n',
        )
        self._write(
            "devices/unit/board/hardware_worker/include/hardware_worker/version.hpp",
            f'#define TXING_UNIT_HARDWARE_WORKER_VERSION "{version}"\n',
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
            self.assertIn(
                'const packageVersion = "1.2.4"',
                (cli.ROOT / "devices/unit/daemon/internal/daemon/version.go").read_text(),
            )
            self.assertIn(
                'kTxingUnitKvsMasterVersion = "1.2.4";',
                (
                    cli.ROOT
                    / "devices/unit/board/kvs_master/include/kvs_master/version.hpp"
                ).read_text(),
            )
            self.assertIn(
                '#define TXING_UNIT_HARDWARE_WORKER_VERSION "1.2.4"',
                (
                    cli.ROOT
                    / "devices/unit/board/hardware_worker/include/hardware_worker/version.hpp"
                ).read_text(),
            )
            self.assertEqual((cli.ROOT / "release/versions/rig").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/lambda").read_text(), "1.2.3\n")
            self.assertEqual((cli.ROOT / "release/versions/office").read_text(), "1.2.3\n")
            self.assertEqual(
                json.loads((cli.ROOT / "office/package.json").read_text())["version"],
                "1.2.3",
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
            self._write(
                "devices/unit/daemon/internal/daemon/version.go",
                'package daemon\n\nconst packageVersion = "1.2.2"\n',
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                cli.bump("unit", "1.2.3")

            self.assertIn("unit managed version sources:", stdout.getvalue())
            self.assertIn("warning:", stderr.getvalue())
            self.assertIn("expected 1.2.3, got '1.2.2'", stderr.getvalue())
            self.assertEqual((cli.ROOT / "release/versions/unit").read_text(), "1.2.3\n")

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


if __name__ == "__main__":
    unittest.main()
