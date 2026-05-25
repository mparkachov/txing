# Public WWW

The public site is strictly static HTML, CSS, and image assets for `txing.dev`.
It is intentionally public-only and does not handle Cognito callbacks or AWS
credentials.

## Current Scope

- minimal `txing.dev` landing page
- sign-in link to the office SPA
- Cloudflare Pages Git publishing
- no package manager, Vite project, build step, version field, or environment variables

The sign-in link points to `https://office.txing.dev/?signin=1`. The office SPA
then starts the PKCE Cognito flow from the office origin, so Cognito returns to
`https://office.txing.dev/`.

## Local Development

```bash
cd www
python3 -m http.server 5174
```

## Cloudflare Pages

- Project: `txing-dev`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `www`
- Build command: `exit 0`
- Deploy command: leave empty
- Build output directory: `.`
- Domain: `txing.dev`
- Environment variables: none
- Build watch paths include: `www/*`
- Build watch paths exclude: empty

If Cloudflare is configured with the repository root as the Pages root instead,
set the build output directory to `www`. With the recommended `www` root
directory, use `.`.

Configure build watch paths in Cloudflare Pages under Settings > Build > Build
watch paths. Cloudflare documents this static-site setup in
[Static HTML](https://developers.cloudflare.com/pages/framework-guides/deploy-anything/),
folder-gated deploys in
[Build watch paths](https://developers.cloudflare.com/pages/configuration/build-watch-paths/),
and domain attachment in
[Custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/).
