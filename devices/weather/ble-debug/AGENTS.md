# Weather BLE debug agent guide

## Scope
- This subproject is a disposable BLE debug harness for the `weather` device type.
- Keep changes isolated under `devices/weather/ble-debug/` unless a shared weather BLE contract change is explicitly required.
- Production Greengrass, Sparkplug, and rig adapter behavior is out of scope here.

## Hardware rules
- Agents may run the `weather-ble-debug` CLI against local BLE hardware.
- Agents may use the CLI to connect, subscribe, write wake/sleep GATT commands, and run idle/wake/sleep/soak tests.
- Agents may run log summarization and firmware build/check targets for named profiles.
- Agents may run the stability matrix script only with `--dry-run`; the real matrix flashes firmware and is user-only.
- Agents must not flash firmware automatically.
- Flash targets in this subproject are manual-only commands for the user.

## BLE debug goals
- Firmware debug work uses the SoftDevice S115 bare-metal stack under `firmware/`.
- Do not replace the debug firmware with a Zephyr Bluetooth app.
- Firmware should remain connected in sleep state.
- A REDCON `3` command should turn the user LED on, report active state, and start one measurement notification per second.
- Wake command response must be observable within 10 seconds.
- REDCON `4` should turn the user LED off and stop the measurement stream.
