# devices/template

Copy this directory when starting a new `txing` device-type project.

Rules:
- This directory is scaffold-only and must not be loaded as a runtime device type.
- Add a real `manifest.toml` only after the new project defines its runtime contracts.
- Keep type-specific code, docs, schemas, and provisioning requirements inside the extracted project.
- Runtime code can be written in any language. Rig-side connectivity should be packaged as Greengrass components that implement the generic v2 capability contract.

Expected structure:
- `aws/`: per-shadow default payloads and schemas for the new device type
- `docs/`: device-type contracts and operator/runtime notes
- `rig/`: optional rig-side Greengrass component implementation in any language
- `web/`: optional React/TypeScript adapter and UI modules compiled into the admin SPA
- `mcu/`: optional firmware/watch-layer implementation
- `board/`: optional device-side board/runtime implementation

Implementation checklist:
- define a stable `type`
- define `device_name` metadata
- declare `capabilities` and matching `[shadows.<name>]` schema/default files
- declare `[web].adapter` if the web UI should show type-specific details
- create a real `manifest.toml`
- add registration-time auxiliary resources, if any
- document shadow ownership and per-subproject contracts
- add runtime tests and provisioning tests
