# Template Rig Runtime

This folder is only an example location. A device type may implement rig-side
runtime logic in Python, Rust, Go, C++, shell, or any other language.

Expose runtime entrypoints as executable commands and list them in
`manifest.toml` under `[[rig.processes]]`.
