# txing agent guide

## Repository structure
- `mcu/`: Rust firmware subproject for the MCU.
- `gw/`: Python subproject for the Raspberry Pi 5 gateway (AWS Greengrass + BLE communication with MCU).

## Working rules
- Treat this repository as a monorepo with the two subprojects above.
- Keep changes scoped to the relevant subproject.
- Do not perform `git commit` automatically.
- Create commits only when explicitly requested by the user.
