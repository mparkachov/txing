# site subproject guide

## Scope
- This directory contains the public static `thing.dev` landing page.

## Notes
- Keep this site public-only. Do not add Cognito callback handling or authenticated admin behavior here.
- The sign-in link should point to the office SPA sign-in entrypoint, normally `https://office.txing.dev/?signin=1`.
- Run package manager and build commands from `site/`.
