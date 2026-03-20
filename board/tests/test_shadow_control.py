from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from board.shadow_control import (
    REPO_ROOT,
    _discover_repo_root,
    _build_shutdown_board_report,
    _build_shadow_update_with_options,
    _extract_desired_board_power_from_delta,
    _extract_desired_board_power_from_shadow,
    _load_validator,
    _validate_shadow_update,
)


class ShadowControlContractTests(unittest.TestCase):
    def test_extracts_desired_board_power_from_shadow_snapshot(self) -> None:
        payload = {
            "state": {
                "desired": {
                    "board": {
                        "power": False,
                    }
                }
            }
        }

        self.assertIs(_extract_desired_board_power_from_shadow(payload), False)

    def test_extracts_desired_board_power_from_delta(self) -> None:
        payload = {
            "state": {
                "board": {
                    "power": False,
                }
            }
        }

        self.assertIs(_extract_desired_board_power_from_delta(payload), False)

    def test_shutdown_update_clears_desired_board_power(self) -> None:
        validator = _load_validator(Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"))
        payload = _build_shadow_update_with_options(
            report=_build_shutdown_board_report(),
            clear_desired_power=True,
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)

    def test_default_shadow_reset_payload_matches_schema(self) -> None:
        validator = _load_validator(Path(REPO_ROOT / "docs" / "txing-shadow.schema.json"))
        payload = json.loads(
            Path(REPO_ROOT / "aws" / "default-shadow.json").read_text(encoding="utf-8")
        )

        _validate_shadow_update(validator, payload)
        self.assertIsNone(payload["state"]["desired"]["mcu"]["power"])
        self.assertIsNone(payload["state"]["desired"]["board"]["power"])
        self.assertIs(payload["state"]["reported"]["mcu"]["power"], False)
        self.assertIs(payload["state"]["reported"]["mcu"]["ble"]["online"], False)
        self.assertIsNone(payload["state"]["reported"]["mcu"]["ble"]["deviceId"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)

    def test_repo_root_detection_uses_board_working_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            board_dir = repo_root / "board"
            docs_dir = repo_root / "docs"
            board_dir.mkdir()
            docs_dir.mkdir()
            (board_dir / "pyproject.toml").write_text("", encoding="utf-8")
            (docs_dir / "txing-shadow.schema.json").write_text("{}", encoding="utf-8")

            installed_module = (
                board_dir
                / ".venv"
                / "lib"
                / "python3.12"
                / "site-packages"
                / "board"
                / "shadow_control.py"
            )
            installed_module.parent.mkdir(parents=True)
            installed_module.write_text("", encoding="utf-8")

            detected = _discover_repo_root(
                cwd=board_dir,
                module_file=installed_module,
                env_repo_root=None,
            )

        self.assertEqual(detected, repo_root.resolve())


if __name__ == "__main__":
    unittest.main()
