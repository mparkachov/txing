# Cyberbrick MAVLink common bindings

The C/C++ headers and TypeScript definitions in this directory are generated
MAVLink 2 `common`-dialect bindings. They are source artifacts, not an Office
npm dependency and not a MAVLink runtime package installed from a registry.

## Pinned inputs

- MAVLink common definitions: `mavlink/c_library_v2`
  [`a3661c0a85dc1de1826f5c95863048af3e2b0d04`](https://github.com/mavlink/c_library_v2/commit/a3661c0a85dc1de1826f5c95863048af3e2b0d04),
  `message_definitions/common.xml` plus its `standard.xml` and `minimal.xml`
  imports.
- Generator: `ArduPilot/pymavlink`
  [`774840a8e6450c33cd97a33b86e3af5d3d1ea173`](https://github.com/ArduPilot/pymavlink/commit/774840a8e6450c33cd97a33b86e3af5d3d1ea173),
  `tools/mavgen.py --lang C --wire-protocol 2.0` and
  `tools/mavgen.py --lang TypeScript --wire-protocol 2.0`.
- Generator Python wheels: `fastcrc==0.3.6` and `lxml==6.1.1`.

The checked-in TypeScript output is mechanically rewritten to replace its
upstream `@ifrunistuttgart/node-mavlink` imports with the local
`typescript/runtime.ts` shim and to prefix generator-emitted continuation lines
in XML descriptions as TypeScript comments. That keeps the generated definition
set usable without adding any runtime MAVLink package to `office/package.json`.

## Layout and license

- `include/mavlink/v2.0/` is the complete generated C/C++ common dialect.
- `typescript/generated/` is the generated TypeScript common definition set.
- `typescript/runtime.ts` and `typescript/frame.ts` are small local adapters
  around that generated output.

The generator's generated-code MIT exception is in
[`LICENSES/pymavlink-generated-MIT.txt`](LICENSES/pymavlink-generated-MIT.txt).
No pymavlink generator source is redistributed here.

## Reproduction

Run this networked, read-only verifier from the repository root:

```sh
just cyberbrick::mavlink::regeneration-check
```

It fetches exactly the two commits above into `./tmp`, regenerates both
languages, applies the documented TypeScript rewrites, and compares the
resulting files with this directory. The generated C build date is normalized
during the comparison because `mavgen` stamps the current date into
`common/version.h`.
