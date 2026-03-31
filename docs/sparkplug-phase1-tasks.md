# Sparkplug Phase 1 Tasks

This checklist tracks the phase-1 Sparkplug lifecycle plan.

- Sparkplug is the only authoritative lifecycle intent transport
- one writable Sparkplug metric: `redcon`
- `town` is the Sparkplug group id
- `rig` is the Sparkplug edge node
- each physical `txing` is one Sparkplug device and one AWS IoT thing
- AWS shadow is reflection and restart cache only
- `mcu.*` and `board.*` remain operational detail only

## 1. Contracts and Docs

- [x] Create `docs/sparkplug-phase1-design.md`
- [x] Create `docs/sparkplug-phase1-tasks.md`
- [x] Update `docs/thing-shadow.md` to distinguish the current shadow compatibility contract from the Sparkplug phase-1 target
- [x] Update `docs/device-rig-shadow-spec.md` or replace it with a rig-centric lifecycle contract
- [x] Document the phase-1 identity mapping for `town`, `rig`, and per-txing thing names
- [x] Document that Sparkplug, not shadow, is the authoritative lifecycle intent path

## 2. Sparkplug Identity and Transport

- [x] Register `rig` as a Sparkplug edge node using its AWS IoT thing/shadow identity
- [x] Register `town` as the Sparkplug group id using its AWS IoT thing/shadow identity
- [x] Register each physical txing as a Sparkplug device using its AWS IoT thing name
- [x] Publish `rig.redcon` through `NBIRTH/NDATA`
- [x] Publish txing `redcon` and `batteryMv` through `DBIRTH/DDATA`
- [x] Accept `DCMD.redcon` with literal values `1..4` as the only lifecycle command

## 3. Txing Lifecycle Reflection

- [x] Add or formalize `state.desired.redcon` on txing shadow as transient Sparkplug intent cache
- [x] Add or formalize `state.reported.redcon` on txing shadow as actual lifecycle state
- [x] Keep `reported.mcu.*` and `reported.board.*` as supporting operational detail
- [x] Remove lifecycle authority from top-level `desired.mcu.power` and `desired.board.power`
- [x] Make rig the only owner of top-level txing `reported.redcon`
- [x] Keep current board and MCU reporting paths as REDCON inputs in phase 1

## 4. Phase 1 REDCON Semantics

- [x] Preserve the current derived txing ladder:
- [x] `REDCON 4` -> BLE reachable, MCU sleep state
- [x] `REDCON 3` -> MCU wakeup state, board not yet phase-1 ready
- [x] `REDCON 2` -> board power + Wi-Fi + video ready, no viewer
- [x] `REDCON 1` -> same as `2`, plus viewer connected
- [x] Keep `REDCON 1` viewer dependency explicitly documented as phase-1 behavior

## 5. Birth, Death, and Recovery

- [x] Emit `DBIRTH` when txing becomes BLE-reachable
- [x] Emit `DDEATH` on the same 30-second BLE timeout used for current `ble.online=false`
- [x] On `DDEATH`, best-effort force txing `reported.redcon=4`
- [x] On `DDEATH`, clear txing `desired.redcon`
- [x] When BLE returns, emit a fresh `DBIRTH`
- [x] After rebirth, reconverge conservatively from observed state instead of trying to restore prior state blindly
- [x] On rig restart, inspect lingering `desired.redcon` and converge conservatively if present

## 6. Rig and Town Reflection

- [x] Reflect `rig.redcon` into rig shadow `state.reported.redcon`
- [x] Keep rig shadow lifecycle reflection to `reported.redcon` only in phase 1
- [x] Reflect static `town.state.reported.redcon=1`
- [x] Keep town lifecycle management out of Sparkplug for phase 1

## 7. UI and Compatibility

- [x] Keep the phase-1 UI as on/off switch plus video button
- [x] Change UI lifecycle behavior so `on` maps to Sparkplug intent `redcon=3`
- [x] Change UI lifecycle behavior so `off` maps to Sparkplug intent `redcon=4`
- [x] Keep direct REDCON selection out of the phase-1 UI
- [x] Keep the current video button behavior unchanged in phase 1
- [x] Make the rest of lifecycle state read-only from the UI perspective

## 8. Explicitly Deferred

- [ ] Additional Sparkplug metrics beyond txing `redcon` and `batteryMv`
- [ ] Town lifecycle command and management through Sparkplug
- [ ] Direct shadow lifecycle control as an authoritative path
- [ ] Automatic mobility or handoff between rigs
- [ ] Re-engineering current board reporting away from the shared shadow path
- [ ] Redefining `REDCON 1` to remove viewer dependency
- [ ] User-facing REDCON selection in the phase-1 UI
