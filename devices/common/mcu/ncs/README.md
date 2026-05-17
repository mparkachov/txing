# nRF Connect SDK Workspace

This directory is the repo-local nRF Connect SDK workspace used by MCU
subprojects that need stock NCS tooling.

Submodule content:

- `../../../../modules/nrfconnect/sdk-nrf/`: Nordic `sdk-nrf` manifest
  repository, pinned by git submodule.

Generated content:

- `.west/`
- `.venv/`
- `.home/`
- `.pip-cache/`
- `.zephyr-cache/`
- `.ccache/`
- `downloads/`
- `sdk/`
- west-managed projects such as `zephyr/`, `modules/`, `nrfxlib/`, and
  `bootloader/`

Use the relevant device justfile target, such as `just power::mcu::install`, to
initialize generated workspace state.
