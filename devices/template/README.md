# devices/template

Copy this directory when starting a new `txing` device-type project.

Rules:
- This directory is scaffold-only and must not be loaded as a runtime device type.
- Add a real `manifest.toml` only after the new project defines its runtime contracts.
- Keep type-specific code, docs, schemas, and provisioning requirements inside the extracted project.

Expected structure:
- `aws/`: default shadow payload and schema for the new device type
- `docs/`: device-type contracts and operator/runtime notes
- `rig/python/`: optional rig-side adapter package
- `web/`: optional web adapter and UI modules
- `mcu/`: optional firmware/watch-layer implementation
- `board/`: optional device-side board/runtime implementation

Implementation checklist:
- define a stable `type`
- define `device_name` metadata
- create a real `manifest.toml`
- add registration-time auxiliary resources, if any
- document shadow ownership and per-subproject contracts
- add runtime tests and provisioning tests
