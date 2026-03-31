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
- [ ] Update `docs/device-gateway-shadow-spec.md` or replace it with a rig-centric lifecycle contract
- [x] Document the phase-1 identity mapping for `town`, `rig`, and per-txing thing names
- [x] Document that Sparkplug, not shadow, is the authoritative lifecycle intent path

## 2. Sparkplug Identity and Transport

- [ ] Register `rig` as a Sparkplug edge node using its AWS IoT thing/shadow identity
- [ ] Register `town` as the Sparkplug group id using its AWS IoT thing/shadow identity
- [ ] Register each physical txing as a Sparkplug device using its AWS IoT thing name
- [ ] Publish `rig.redcon` through `NBIRTH/NDATA`
- [ ] Publish txing `redcon` and `batteryMv` through `DBIRTH/DDATA`
- [ ] Accept `DCMD.redcon` with literal values `1..4` as the only lifecycle command

## 3. Txing Lifecycle Reflection

- [ ] Add or formalize `state.desired.redcon` on txing shadow as transient Sparkplug intent cache
- [ ] Add or formalize `state.reported.redcon` on txing shadow as actual lifecycle state
- [ ] Keep `reported.mcu.*` and `reported.board.*` as supporting operational detail
- [ ] Remove lifecycle authority from top-level `desired.mcu.power` and `desired.board.power`
- [ ] Make rig the only owner of top-level txing `reported.redcon`
- [ ] Keep current board and MCU reporting paths as REDCON inputs in phase 1

## 4. Phase 1 REDCON Semantics

- [ ] Preserve the current derived txing ladder:
- [ ] `REDCON 4` -> BLE reachable, MCU sleep state
- [ ] `REDCON 3` -> MCU wakeup state, board not yet phase-1 ready
- [ ] `REDCON 2` -> board power + Wi-Fi + video ready, no viewer
- [ ] `REDCON 1` -> same as `2`, plus viewer connected
- [ ] Keep `REDCON 1` viewer dependency explicitly documented as phase-1 behavior

## 5. Birth, Death, and Recovery

- [ ] Emit `DBIRTH` when txing becomes BLE-reachable
- [ ] Emit `DDEATH` on the same 30-second BLE timeout used for current `ble.online=false`
- [ ] On `DDEATH`, best-effort force txing `reported.redcon=4`
- [ ] On `DDEATH`, clear txing `desired.redcon`
- [ ] When BLE returns, emit a fresh `DBIRTH`
- [ ] After rebirth, reconverge conservatively from observed state instead of trying to restore prior state blindly
- [ ] On rig restart, inspect lingering `desired.redcon` and converge conservatively if present

## 6. Rig and Town Reflection

- [ ] Reflect `rig.redcon` into rig shadow `state.reported.redcon`
- [ ] Keep rig shadow lifecycle reflection to `reported.redcon` only in phase 1
- [ ] Reflect static `town.state.reported.redcon=1`
- [ ] Keep town lifecycle management out of Sparkplug for phase 1

## 7. UI and Compatibility

- [ ] Keep the phase-1 UI as on/off switch plus video button
- [ ] Change UI lifecycle behavior so `on` maps to Sparkplug intent `redcon=3`
- [ ] Change UI lifecycle behavior so `off` maps to Sparkplug intent `redcon=4`
- [ ] Keep direct REDCON selection out of the phase-1 UI
- [ ] Keep the current video button behavior unchanged in phase 1
- [ ] Make the rest of lifecycle state read-only from the UI perspective

## 8. Explicitly Deferred

- [ ] Additional Sparkplug metrics beyond txing `redcon` and `batteryMv`
- [ ] Town lifecycle command and management through Sparkplug
- [ ] Direct shadow lifecycle control as an authoritative path
- [ ] Automatic mobility or handoff between rigs
- [ ] Re-engineering current board reporting away from the shared shadow path
- [ ] Redefining `REDCON 1` to remove viewer dependency
- [ ] User-facing REDCON selection in the phase-1 UI
