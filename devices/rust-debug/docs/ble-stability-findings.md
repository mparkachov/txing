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

## Current Best Candidate

Current candidate:

```text
MCU profile:      gatt-1280-tx0
Rig conn profile: stable-100-0-20
Service filter:   --require-service
```

Reason:

- `gatt-1280-tx0` passed all focused `stable-100-0-20` service-filter tests
  seen so far: 23/23.
- It had only two recovered `le-connection-abort-by-local` retries across those
  23 tests.
- It had no service discovery timeout, wake timeout, sleep timeout, missing
  battery update, or unexpected disconnect failure.
- Worst observed connect time was about 8.1 seconds, which is acceptable for the
  current use case.
- Current draw is lower than `tx8`, and `tx0` did not look less stable than
  `tx4` in the collected data.

## Observed Runs

Copied logs are under `tmp/rust-debug-rig-test-results/`.

New physical Rust test runs write structured artifacts next to `cycle.log`:

- `results.jsonl`: one JSON record per generated Rust test case.
- `results.json`: aggregate summary with copied testcase records.
- `junit.xml`: JUnit-compatible report for CI/test reporters.

The logs summarized below were copied before those structured artifacts existed,
so their results were read from `cycle.log`.

| Log directory | MCU profile | Rig profile(s) | Result | Notes |
| --- | --- | --- | --- | --- |
| `20260509-075055-wzzvZn` | `gatt-320-tx8` | `fast-50-0-20`, `stable-100-0-20`, `stable-125-0-20` | 45/45 passed | Name-only discovery. `fast-50` had 7 retries, `stable-100` had 1, `stable-125` had 0. |
| `20260509-083329-UnK4N4` | `gatt-320-tx8` | `stable-100-0-20`, `stable-125-0-20` | `stable-100`: 10/10, `stable-125`: 1/10 | Service-filter discovery. `stable-125` failed badly with connect/service-discovery and active-window failures. |
| `20260509-085529-9HqCev` | `gatt-1280-tx4` | `stable-100-0-20` | 8/8 passed | No retries. Connect average 4.6 s, max 7.8 s. |
| `20260509-090322-YXjaTR` | `gatt-1280-tx0` | `stable-100-0-20` | 8/8 passed | One recovered connect retry. Connect average 3.6 s, max 6.6 s. |
| `20260509-091045-ZSUp6u` | `gatt-1280-tx0` | `stable-100-0-20` | 15/15 passed | One recovered connect retry. Connect average 4.5 s, max 8.1 s. |
| `20260509-093036-pLYWEN` | `gatt-1280-tx4` | `stable-100-0-20` | 13/15 passed | One recovered retry. Two failures occurred after successful connection and wake. |

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

This is the strongest current evidence for a low-current stable configuration.

### gatt-1280-tx4

`gatt-1280-tx4` passed the first 8-test screen, but failed 2 of 15 in the later
confirm run:

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
The collected data should not be interpreted as proof that `tx4` improves the
connected-state link. In this data, `tx4` had active-window failures while
`tx0` did not.

## Working Conclusions

- Use `stable-100-0-20` as the rig connection profile for the current firmware.
- Do not use `stable-125-0-20` for this setup.
- Prefer `gatt-1280-tx0` over `gatt-1280-tx4` based on current stability and
  current draw evidence.
- Treat `gatt-1280-tx4` as inconclusive or rejected until it can pass a clean
  confirm run; it currently has active-window failures.
- Avoid `gatt-320-tx8` unless faster first-connect behavior is more important
  than current draw. It is stable with `stable-100-0-20`, but `tx8` current is
  visibly higher.

## Next Test If More Confidence Is Needed

No further tests have been run after the logs above. The next focused confidence
test should be only the current best candidate:

```sh
just rust-debug::rig::test 30 weather-q8zbgb \
  --conn-profile stable-100-0-20 \
  --scan-timeout 90 \
  --connect-timeout 45 \
  --connect-attempts 4 \
  --retry-delay 3 \
  --disconnect-deadline 10 \
  --require-service
```

Acceptance suggestion:

- 30/30 tests pass.
- No service discovery timeouts.
- No active-window failures after `wake-ok`.
- A small number of recovered `le-connection-abort-by-local` retries is
  acceptable if every test still completes the full wake/sleep cycle.

If the 30-test `tx0` run fails in the same post-wake battery-update pattern,
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
