# Public Site

The public site is a static Vite page for `thing.dev`. It is intentionally
public-only and does not handle Cognito callbacks or AWS credentials.

## Current Scope

- minimal `thing.dev` landing page
- sign-in link to the office SPA
- Cloudflare Pages Git deployment

The sign-in link points to `https://office.txing.dev/?signin=1`. The office SPA
then starts the PKCE Cognito flow from the office origin, so Cognito returns to
`https://office.txing.dev/`.

## Local Development

```bash
cd site
bun install
bun run dev
```

Manual fallback:

```bash
cp site/.env.example site/.env.local
```

## Cloudflare Pages

- Project: `thing-dev`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `site`
- Build command: `bun install --frozen-lockfile && bun --bun run build`
- Deploy command: leave empty; Cloudflare Pages publishes `dist`
- Build output directory: `dist`
- Domain: `thing.dev`
- Environment variables:
  - `BUN_VERSION=1.3.11`
  - `VITE_OFFICE_SIGNIN_URL=https://office.txing.dev/?signin=1`
