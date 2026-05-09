# BLE Stability Findings

Date: 2026-05-09

This note records the current physical BLE findings for the Rust rig against the
`ble-debug` MCU GATT firmware. The goal is to identify a stable low-current
configuration, not to improve the Rust test tool.

## Test Contract

All focused tests used the Rust physical test harness with one wake/sleep cycle
per Rust test case. The relevant stable rig command shape was:

```sh
just rust-debug::rig::test N weather-q8zbgb \
  --conn-profile stable-100-0-20 \
  --scan-timeout 90 \
  --connect-timeout 45 \
  --connect-attempts 4 \
  --retry-delay 3 \
  --disconnect-deadline 10 \
  --require-service
```

`--require-service` means scan discovery accepts an advertisement only when the
local name matches `weather-q8zbgb` and the weather service UUID is visible in
the advertised service UUID list. It does not change GATT commands, connection
parameters, wake/sleep behavior, or post-connect service discovery.

## Current Preferred Candidate

Current candidate:

```text
MCU profile:      gatt-1280-tx4
Rig conn profile: stable-100-0-20
Service filter:   --require-service
```

Reason:

- The latest `gatt-1280-tx4` service-filter run passed 45/45 tests with
  `stable-100-0-20`.
- It had six recovered `le-connection-abort-by-local` retries across those 45
  tests.
- It had no service discovery timeout, wake timeout, sleep timeout, missing
  battery update, or unexpected disconnect failure in the 45-test run.
- Worst observed connect time in that run was about 5.4 seconds, which is
  acceptable for the current use case.
- `gatt-1280-tx0` had a clean 23/23 stability result, but its observed RSSI was
  judged too low for the current physical setup.
- Current draw difference between `tx0` and `tx4` is small enough that the extra
  radio margin of `tx4` is preferred. `tx8` remains visibly higher current.

## Observed Runs

Copied logs are under `tmp/rust-debug-rig-test-results/`.

New physical Rust test runs write structured artifacts next to `cycle.log`:

- `results.jsonl`: one JSON record per generated Rust test case.
- `results.json`: aggregate summary with copied testcase records.
- `junit.xml`: JUnit-compatible report for CI/test reporters.

Older logs summarized below were copied before those structured artifacts
existed, so their results were read from `cycle.log`. The latest 45-test `tx4`
run has `results.json`, `results.jsonl`, and `junit.xml`.

| Log directory | MCU profile | Rig profile(s) | Result | Notes |
| --- | --- | --- | --- | --- |
| `20260509-075055-wzzvZn` | `gatt-320-tx8` | `fast-50-0-20`, `stable-100-0-20`, `stable-125-0-20` | 45/45 passed | Name-only discovery. `fast-50` had 7 retries, `stable-100` had 1, `stable-125` had 0. |
| `20260509-083329-UnK4N4` | `gatt-320-tx8` | `stable-100-0-20`, `stable-125-0-20` | `stable-100`: 10/10, `stable-125`: 1/10 | Service-filter discovery. `stable-125` failed badly with connect/service-discovery and active-window failures. |
| `20260509-085529-9HqCev` | `gatt-1280-tx4` | `stable-100-0-20` | 8/8 passed | No retries. Connect average 4.6 s, max 7.8 s. |
| `20260509-090322-YXjaTR` | `gatt-1280-tx0` | `stable-100-0-20` | 8/8 passed | One recovered connect retry. Connect average 3.6 s, max 6.6 s. |
| `20260509-091045-ZSUp6u` | `gatt-1280-tx0` | `stable-100-0-20` | 15/15 passed | One recovered connect retry. Connect average 4.5 s, max 8.1 s. |
| `20260509-093036-pLYWEN` | `gatt-1280-tx4` | `stable-100-0-20` | 13/15 passed | One recovered retry. Two failures occurred after successful connection and wake. |
| `20260509-100432-3j3Aa9` | `gatt-1280-tx4` | `stable-100-0-20` | 45/45 passed | Structured run. Six recovered connect retries. Connect average 3.3 s, max 5.4 s. Wake max 293 ms. No active-window failures. |

## Details

### gatt-320-tx8

`stable-100-0-20` is the only rig connection profile that stayed consistently
clean when `--require-service` was enabled. `stable-125-0-20` should not be used
for the current setup: it passed in a name-only run, but failed 9 of 10 tests
with service-filter discovery. The failures were not simple missing
advertisements; several reached connection or wake and then failed later.

`fast-50-0-20` passed, but produced more recovered connection retries than
`stable-100-0-20`, so it is not the preferred stable profile.

### gatt-1280-tx0

`gatt-1280-tx0` passed the 8-test screen and the 15-test confirm run with
`stable-100-0-20` and `--require-service`. Combined result:

```text
tests:      23
passed:     23
failed:      0
retries:     2
connect avg: ~4.2 s
connect max: ~8.1 s
```

This remains the strongest current evidence for the lowest-current stable
configuration. However, RSSI observed from the logs was judged too low for the
current physical setup, so `tx0` is no longer the preferred practical choice.

### gatt-1280-tx4

`gatt-1280-tx4` passed the first 8-test screen, failed 2 of 15 in the next
confirm run, then passed the latest 45-test run.

First confirm failure:

```text
tests:      15
passed:     13
failed:      2
retries:     1
connect avg: ~5.0 s
connect max: ~8.1 s
```

Both failures happened after successful advertisement discovery, connection,
service discovery, notify enablement, and wake. They were active-window failures:

- Test 14 reached `wake-ok`, then received only two active battery updates and
  never completed sleep.
- Test 15 reached `wake-ok`, then received no active battery updates before the
  next test began.

That pattern is not explained by `--require-service`, because service filtering
is only part of pre-connect discovery.

In the current firmware, `BLE_DEBUG_ADV_TX_POWER_DBM` is applied with
`BT_HCI_VS_LL_HANDLE_TYPE_ADV`, so it clearly controls advertising TX power.
This should not be interpreted as proof that `tx4` directly improves the
connected-state link.

Latest 45-test confirm:

```text
tests:       45
passed:      45
failed:       0
retries:      6
connect avg: ~3.3 s
connect max: ~5.4 s
wake max:    293 ms
sleep max:   273 ms
RSSI sample: -81 dBm
```

The latest run is strong enough to make `tx4` the current practical candidate
when `tx0` RSSI is considered too low and `tx8` current is visibly higher.

## Working Conclusions

- Use `stable-100-0-20` as the rig connection profile for the current firmware.
- Do not use `stable-125-0-20` for this setup.
- Prefer `gatt-1280-tx4` for the current physical setup because the latest
  45-test run is clean, `tx0` RSSI is too low, and `tx4` current is close to
  `tx0`.
- Keep `gatt-1280-tx0` as the lowest-current fallback only if RSSI margin is
  acceptable in the target enclosure/location.
- Treat the earlier `gatt-1280-tx4` 13/15 run as a warning that one more long
  confirm run is useful before declaring it final, but do not reject `tx4`
  based on the current evidence.
- Avoid `gatt-320-tx8` unless faster first-connect behavior is more important
  than current draw. It is stable with `stable-100-0-20`, but `tx8` current is
  visibly higher.

## Next Test If More Confidence Is Needed

The next focused confidence test, if needed, should be only the current
preferred candidate:

```sh
just rust-debug::rig::test 45 weather-q8zbgb \
  --conn-profile stable-100-0-20 \
  --scan-timeout 90 \
  --connect-timeout 45 \
  --connect-attempts 4 \
  --retry-delay 3 \
  --disconnect-deadline 10 \
  --require-service
```

Acceptance suggestion:

- 45/45 tests pass.
- No service discovery timeouts.
- No active-window failures after `wake-ok`.
- A small number of recovered `le-connection-abort-by-local` retries is
  acceptable if every test still completes the full wake/sleep cycle.

If a future `tx4` run fails again in the same post-wake battery-update pattern,
the next variable to test is connection-parameter behavior, not TX power:

```sh
just rust-debug::rig::test 10 weather-q8zbgb \
  --conn-profile central-default \
  --scan-timeout 90 \
  --connect-timeout 45 \
  --connect-attempts 4 \
  --retry-delay 3 \
  --disconnect-deadline 10 \
  --require-service
```
