# www subproject guide

## Scope
- This directory contains the public static `txing.dev` web site.

## Rules
- Read `../docs/constraints/repository-rules.md` before changing public-site
  hosting or Cloudflare behavior.
- Keep this site strictly static HTML, CSS, and image assets.
- Do not add Vite, package manager files, JavaScript build steps, runtime auth, Cognito callback handling, AWS credentials, or version metadata.
- The sign-in link should point to the office SPA sign-in entrypoint: `https://office.txing.dev/?signin=1`.
- Cloudflare Pages should deploy this site only when `www/*` changes.
