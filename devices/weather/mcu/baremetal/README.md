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

Use the repo-local nRF Connect SDK Bare Metal workspace:

```sh
just common::nrf_bm::install
```

It checks out Nordic's BM workspace under:

```text
devices/common/mcu/nrf-bm/workspace
```

Then build from this repository:

```sh
cd /Users/Maxim/Developer/txing
just weather::mcu::bm-check
```

The provisional board target is:

```text
bm_nrf54l15dk/nrf54l15/cpuapp/s115_softdevice
```

The Seeed XIAO nRF54L15 is not yet modeled as a bare-metal board in this
repository. This milestone avoids board pins and sensors so the DK target is
used only to select the nRF54L15 CPU application core and S115 SoftDevice.

## Manual Flashing Only

Agents must not flash this firmware. The application expects the existing
`TXW1` factory-data record to remain in flash.

Current build outputs:

```text
Application HEX:
devices/weather/mcu/build/baremetal-advertising/baremetal/zephyr/zephyr.hex

S115 HEX:
devices/common/mcu/nrf-bm/workspace/nrf-bm/components/softdevice/nrf54l/s115/s115_nrf54l15_10.0.0_softdevice.hex
```

Flash the application with the repo-local BM wrapper:

```sh
just weather::mcu::bm-flash-app
```

On a clean board, flash S115 first:

```sh
just weather::mcu::bm-flash-softdevice
```

The BM flash targets do not write the `TXW1` factory record. Preserve the
existing record, or write it with the Zephyr-era flashing flow before using the
advertising-only BM image on a clean board.

Agents must not run flash targets. Use them only manually with the intended
board connected.

After manual flashing, check advertising with:

```sh
sudo btmon | grep -a 'weather-q8zbgb'
```

or:

```sh
bluetoothctl
scan on
```
