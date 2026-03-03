# txing

Monorepo root for `txing`.

- MCU firmware lives in `mcu/` (Rust).
- Gateway software lives in `gw/` (Python, AWS Greengrass + BLE bridge).
- Shared docs live in `docs/`.

Run commands from the relevant subproject.

Firmware example:

```bash
cd mcu
cargo mcu build
```

Gateway example:

```bash
cd gw
uv run gw
```
