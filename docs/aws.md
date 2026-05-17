# AWS

This guide covers the staged AWS bring-up for a clean txing environment. The AWS
flow is intentionally stateless: recipes do not write repo-local operational
state, generated AWS config files, or hidden certificate paths.

Prefer the AWS CLI for control-plane work. The `just aws-town ...`,
`just aws-rig ...`, and `just aws-device ...` recipes are thin wrappers around
`aws` with `config/aws.env` and `config/aws.credentials` applied.
Install AWS CLI v2 using the official AWS installer; do not use the OS
repository `awscli` package.

## Local Config

Initialize and edit only these files:

```bash
cp config/aws.env.example config/aws.env
cp config/aws.credentials.example config/aws.credentials
```

`config/aws.env` is the single non-secret AWS access/config file. It defines
the AWS region/source profile, base stack name, optional selected generated
thing IDs (`TXING_TOWN_ID`, `TXING_RIG_ID`, `TXING_THING_ID`), Cognito admin
settings, and local board/rig runtime settings. It does not define an SSM
catalog root; the type catalog root is always `/txing`.

`config/aws.credentials` contains the source AWS access keys only. Do not create
repo-local generated AWS profile files; recipes resolve stack outputs and AWS IoT
registry values live.

## Bring-Up Order

Run the setup in this order:

```bash
just aws::deploy
just aws::deploy-town town
just aws::deploy-rig <town-id> raspi server
just aws::deploy-device <rig-id> unit bot
```

`just aws::deploy` deploys the base root stack. That root stack owns Cognito
for web authentication, common IoT policies, artifact buckets, the Sparkplug
witness, Fleet Indexing, shared rig/device runtime IAM, AWS IoT ThingTypes, and
the SSM type catalog. Web hosting is externalized to Cloudflare Pages. The type
catalog is CloudFormation-managed under `/txing` as leaf parameters such as
`/txing/town/cloud/time/kind` and
`/txing/town/cloud/time/capabilities`.

`just aws::deploy-town <town-name>` idempotently creates or updates only the
town thing with ThingType `town` and its `sparkplug` shadow. It prints the
generated town thing ID.

`just aws::deploy-rig <town-id> <rig-type> <rig-name>` idempotently creates or
updates only the rig thing with ThingType `raspi` or `cloud` plus the rig
`sparkplug` shadow. Shared Greengrass token exchange and runtime IAM are base
stack outputs.

`just aws::deploy-device <rig-id> <device-type> <device-name>` idempotently
creates or updates only the device thing, named shadows, and optional
per-instance resources. Device enrollment validates compatibility by requiring
the SSM leaf `/txing/town/<rig-type>/<device-type>/kind`. Concrete instance data
stays in AWS IoT thing attributes and named shadows, not SSM.

## Web Admin

Create or update the Cognito admin user after `aws::deploy`:

```bash
just aws::create-admin-user '<strong-password>'
```

Generate and build the SPA:

```bash
just web::write-env
just web::build
```

`web::write-env` is allowed to write `web/.env.local` because it is a web build
input derived from live stack outputs. Production hosting is handled manually in
Cloudflare Pages:

- Project: `txing-office`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `web`
- Build command: `bun install --frozen-lockfile && bun --bun run build`
- Deploy command: leave empty; do not use `npx wrangler deploy`
- Build output directory: `dist`
- Domain: `office.txing.dev`
- Environment variables:
  - `BUN_VERSION=1.3.11`
  - `VITE_AWS_REGION`
  - `VITE_TOWN_THING_NAME`
  - `VITE_SPARKPLUG_GROUP_ID`
  - `VITE_COGNITO_DOMAIN`
  - `VITE_COGNITO_CLIENT_ID`
  - `VITE_COGNITO_USER_POOL_ID`
  - `VITE_COGNITO_IDENTITY_POOL_ID`
  - `VITE_IOT_POLICY_NAME`
  - `VITE_COGNITO_SCOPE`
  - `VITE_ADMIN_EMAIL`

Do not set `VITE_TXING_VERSION`, `VITE_DEVICE_THING_NAME`, or
`VITE_SPARKPLUG_EDGE_NODE_ID` in Cloudflare. The version is injected by the Vite
build from the root `VERSION` file, and the admin SPA discovers rigs and devices
from the configured town.

The base stack parameter `WebAppUrl` defaults to `https://office.txing.dev`.
Cognito callback and logout URLs are:

- `https://office.txing.dev/`
- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

Public `thing.dev` is a separate Cloudflare Pages project:

- Project: `thing-dev`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `site`
- Build command: `bun install --frozen-lockfile && bun --bun run build`
- Deploy command: leave empty; do not use `npx wrangler deploy`
- Build output directory: `dist`
- Domain: `thing.dev`
- Environment variables:
  - `BUN_VERSION=1.3.11`
  - `VITE_OFFICE_SIGNIN_URL=https://office.txing.dev/?signin=1`

## Runtime Checks

Validate runtime access:

```bash
just rig::check <rig-id>
just unit::board::check
```

Production rig services run as Greengrass Lite components. Local command wrappers
use `config/aws.env` and live AWS resolution; they do not depend on generated
local AWS config files.

## Important Naming Rule

IAM roles, IAM managed policies, IoT role aliases, and IoT policies use
CloudFormation-generated physical names. Do not depend on old fixed names such as
`town-rig-runtime` or `town-rig-device-policy`; use stack outputs or AWS API
lookups.

## Shadow Inspection

Inspect shadows for the configured device by default:

```bash
just aws::shadow
just aws::shadow '' sparkplug
```

Inspect a specific thing:

```bash
just aws::shadow <thing-name>
just aws::shadow <thing-name> sparkplug
```

Reset a named shadow. Responses go to stdout unless you pass an explicit output
path to `init-shadow`.

```bash
just aws::shadow-reset <thing-name> sparkplug
just aws::init-shadow <thing-name> sparkplug
```

## Certificates

`aws::cert` is rig-focused. It resolves the rig thing by generated thing ID,
creates a new active AWS IoT certificate,
attaches the base stack IoT policy, attaches the certificate to the rig thing,
and writes material under `config/certs/rig/`.

```bash
just aws::cert <rig-id>
```

Generated files:

- `config/certs/rig/rig.cert.pem`
- `config/certs/rig/rig.public.key`
- `config/certs/rig/rig.private.key`
- `config/certs/rig/rig.cert.arn`
- `config/certs/rig/AmazonRootCA1.pem`

`config/certs/` is explicitly ignored by git. The recipe refuses to overwrite
existing material; move or delete the files first if you intentionally rotate the
rig certificate. On a stable rig host, `txing-greengrass-lite` is read-only; use
the copied certificate and private key during manual Greengrass Lite host
configuration.

## Cleanup

For a full teardown, delete resources in reverse dependency order:

```bash
just aws-town cloudformation delete-stack --stack-name "$AWS_STACK_NAME"
```

The base stack has delete-time cleanup custom resources for disposable S3 bucket
contents and IoT policy attachments created outside CloudFormation, such as rig
certificates and browser Cognito identities. You should not need to manually
empty `GreengrassArtifactsBucketName`, and the base IoT policies should be
detached from their principals before CloudFormation deletes the policy
resources.

Legacy AWS-hosted web stacks previously owned `WebAppBucketName` and
`WebAppDistributionId`. Current CloudFormation removes those resources because
production web hosting is on Cloudflare Pages. During the first update from an
older stack, if CloudFormation cannot delete the old web bucket because it is
not empty, manually empty only that old web bucket and retry the stack update.

CloudFormation packaging buckets are intentionally created outside the stack so
`aws cloudformation package` can upload templates before a stack exists. Delete
those unmanaged artifact buckets explicitly after stack teardown:

```bash
just aws::delete-packaging-buckets
```

This removes the shared `txing-cfn-<account>-<region>-<stack>` bucket and the
legacy `txing-time-lambda-<account>-<region>` bucket if either exists. Current
time Lambda deployment reuses the shared `txing-cfn-*` packaging bucket by
default.

Generated IoT things, per-device time Lambda stacks, and KVS signaling channels
are still instance resources. Delete those separately if you want the account
back to a fully empty state.
