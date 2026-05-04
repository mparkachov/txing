# Weather Bare-Metal Advertising Firmware

This is the first S115 bare-metal replacement milestone for the weather MCU.
It intentionally does only one thing:

1. Read the existing factory data record at `0x000f0000`.
2. Validate the `TXW1` magic, version, printable AWS IoT Thing name, and CRC32.
3. Set the GAP device name to that Thing name.
4. Start connectable BLE advertising with the full local name in primary advertising data.

There is no BME280 support, no txing weather GATT service, and no sleep-state
rendezvous logic yet. The acceptance test for this milestone is that a flashed
image makes `btmon` or `bluetoothctl` show the AWS IoT Thing name, for example
`weather-q8zbgb`.

## SDK

Use Nordic's nRF Connect SDK Bare Metal workspace, not the Zephyr workspace
under this repository:

```sh
west init -m https://github.com/nrfconnect/sdk-nrf-bm --mr v2.0.0 ~/Downloads/nrf-bm-v2.0.0
cd ~/Downloads/nrf-bm-v2.0.0
west update
```

This workspace also uses a small tool venv for CMake and Ninja:

```sh
python3 -m venv ~/Downloads/nrf-bm-tools
~/Downloads/nrf-bm-tools/bin/pip install 'cmake<4' ninja
```

Then build from this repository. `ZEPHYR_SDK_INSTALL_DIR` points at the Zephyr
SDK already used by the repo's Zephyr workspace.

```sh
cd /Users/Maxim/Developer/txing
PATH="$HOME/Downloads/nrf-bm-tools/bin:$PWD/zephyr/.venv/bin:$PATH" \
ZEPHYR_SDK_INSTALL_DIR="$PWD/zephyr/sdk/zephyr-sdk-0.17.4" \
ZEPHYR_TOOLCHAIN_VARIANT=zephyr \
NRF_BM_ROOT="$HOME/Downloads/nrf-bm-v2.0.0" \
just --justfile devices/weather/mcu/justfile bm-check
```

The provisional board target is:

```text
bm_nrf54l15dk/nrf54l15/cpuapp/s115_softdevice
```

The Seeed XIAO nRF54L15 is not yet modeled as a bare-metal board in this
repository. This milestone avoids board pins and sensors so the DK target is
used only to select the nRF54L15 CPU application core and S115 SoftDevice.

## Manual Flashing Only

Agents must not flash this firmware. After a successful build, manually combine
the application image with the S115 SoftDevice and the existing factory-data
record as needed for the board programming flow.

Current build outputs:

```text
Application HEX:
devices/weather/mcu/build/baremetal-advertising/baremetal/zephyr/zephyr.hex

S115 HEX:
~/Downloads/nrf-bm-v2.0.0/nrf-bm/components/softdevice/nrf54l/s115/s115_nrf54l15_10.0.0_softdevice.hex
```

After manual flashing, check advertising with:

```sh
sudo btmon | grep -a 'weather-q8zbgb'
```

or:

```sh
bluetoothctl
scan on
```
