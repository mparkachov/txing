# Public Site

Static public landing page for `thing.dev`.

## Local Development

```bash
bun install
bun run dev
```

## Cloudflare Pages

- Project: `thing-dev`
- Root directory: `site`
- Build command: `bun --bun run build`
- Build output directory: `dist`
- Domain: `thing.dev`
- Environment variables:
  - `BUN_VERSION=1.3.11`
  - `VITE_OFFICE_SIGNIN_URL=https://office.txing.dev/?signin=1`
