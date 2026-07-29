# Device-owned entry point for the shared board implementation.
device := "unit"
board_justfile := canonicalize(source_directory() / ".." / "common" / "board" / "justfile")

import '../common/board/device-recipes.just'
