from __future__ import annotations

import importlib
import sys
import unittest


class BoardPackageInitTests(unittest.TestCase):
    def test_board_package_does_not_import_shadow_control_eagerly(self) -> None:
        sys.modules.pop("board", None)
        sys.modules.pop("board.shadow_control", None)

        board_package = importlib.import_module("board")

        self.assertTrue(callable(board_package.main))
        self.assertNotIn("board.shadow_control", sys.modules)


if __name__ == "__main__":
    unittest.main()
