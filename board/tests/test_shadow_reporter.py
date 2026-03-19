from __future__ import annotations

import unittest
from pathlib import Path

from board.shadow_reporter import (
    REPO_ROOT,
    _build_shutdown_board_report,
    _build_shadow_update_with_options,
    _extract_desired_board_power_from_delta,
    _extract_desired_board_power_from_shadow,
    _load_validator,
    _validate_shadow_update,
)


class ShadowReporterContractTests(unittest.TestCase):
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
        self.assertIsNone(payload["state"]["desired"]["board"]["online"])
        self.assertIs(payload["state"]["reported"]["board"]["power"], False)
        self.assertIs(payload["state"]["reported"]["board"]["wifi"]["online"], False)
        self.assertIsNone(payload["state"]["reported"]["board"]["online"])


if __name__ == "__main__":
    unittest.main()
