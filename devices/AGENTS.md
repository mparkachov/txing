# Device subprojects guide

This guide applies to every device subproject. Read the nearest nested
`AGENTS.md` before editing a device-specific component.

## Standard development process

- Follow the repository-wide GitHub Milestone and Issue workflow in
  `../AGENTS.md`.
- Read `../docs/agent-guidance/spec-driven-development.md` before planning or
  starting implementation. It defines the required plan closeout, Issue
  selection, and one-active-Issue discipline.
- Keep device-specific contracts, provisioning, hardware, and validation
  guidance in the relevant device documentation. Do not duplicate the shared
  tracker process in device READMEs.
- For MCU work, read the owning device's README and
  `../docs/components/mcu.md` before changing firmware. For the current `unit`
  device type, the device-level MCU contract is in `unit/README.md`.

## Documentation structure

- Each device type has a root `README.md` as its entry point for the device
  contract, component boundaries, operator-facing commands, and links to its
  detailed contracts.
- Nested component READMEs hold focused build or runtime instructions. Nested
  `AGENTS.md` files are reserved for additional local agent constraints that do
  not belong in user-facing documentation.
