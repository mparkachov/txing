# Device-scoped board recipes.
#
# Each device type imports this file from its own `board.just` with `device` and
# `board_justfile` bound, and exposes it as `mod board`, so a device-scoped board
# operation reads the same as a device-scoped MCU operation:
#
#   just unit::board::nerdctl-build     just unit::mcu::build
#
# Everything here delegates into the shared implementation in
# devices/common/board/justfile with the device pre-bound, including its
# `_require-device` validation. Operations that are genuinely device-independent
# stay common-owned there and are not listed here; `just common::board::proto-gen`
# is the board counterpart to `just mcu::check`.

@role-policy thing_id='':
    just --justfile "{{board_justfile}}" role-policy "{{device}}" "{{thing_id}}"

@test:
    just --justfile "{{board_justfile}}" test "{{device}}"

@run:
    just --justfile "{{board_justfile}}" run "{{device}}"

@hardware-build-native:
    just --justfile "{{board_justfile}}" hardware-build-native "{{device}}"

@hardware-test-native:
    just --justfile "{{board_justfile}}" hardware-test-native "{{device}}"

@daemon-build-alpine:
    just --justfile "{{board_justfile}}" daemon-build-alpine "{{device}}"

@hardware-build-alpine:
    just --justfile "{{board_justfile}}" hardware-build-alpine "{{device}}"

@mavlink-build-alpine:
    just --justfile "{{board_justfile}}" mavlink-build-alpine "{{device}}"

@nerdctl-build:
    just --justfile "{{board_justfile}}" nerdctl-build "{{device}}"

@nerdctl-smoke:
    just --justfile "{{board_justfile}}" nerdctl-smoke "{{device}}"

@clean:
    just --justfile "{{board_justfile}}" clean "{{device}}"
