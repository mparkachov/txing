# AWS

This guide covers the staged AWS bring-up for a clean txing environment. The AWS
flow is intentionally stateless: recipes do not write repo-local operational
state, generated AWS config files, or hidden certificate paths.

Prefer the AWS CLI for control-plane work. The `just aws-town ...`,
`just aws-rig ...`, and `just aws-device ...` recipes are thin wrappers around
plain `aws` calls. Txing identifiers come from environment variables or explicit
positional recipe arguments.
Install operator CLIs with mise if they are not already available:

```bash
mise use --global aws-cli@latest jq@latest
```

## Native AWS Config

AWS account, credentials, selected profile, and region come from native AWS CLI
configuration. Verify the operator shell can resolve both before running stack
recipes:

```bash
aws configure get region
aws sts get-caller-identity
```

Set `TXING_AWS_STACK` explicitly before running stack-backed commands such as
`just aws::deploy`, `just aws::publish`, `just aws::publish-lambda`,
`just aws::check`, `just office::write-env`, `just rig::cert`, and
`just unit::cert`.
Export it in the operator shell or pass a positional stack name to recipes that
accept one. Those commands fail if `TXING_AWS_STACK` is unset and no positional
stack name is provided.
`TXING_AWS_STACK` is the environment prefix, for example `town`; the base
CloudFormation stack is derived as `<TXING_AWS_STACK>-aws-base`, for example
`town-aws-base`.
Optional selected generated thing IDs (`TXING_TOWN_ID`, `TXING_RIG_ID`,
`TXING_THING_ID`) also come from the operator shell. Web/admin deploy parameters
are initialized with `aws::deploy-init`; the type catalog root is always
`/txing`. Recipes resolve operational stack values from SSM Parameter Store and
AWS IoT registry values live.

## Bring-Up Order

Run the setup in this order:

```bash
export TXING_AWS_STACK=town
cp shared/aws/deploy-init.example.json shared/aws/deploy-init.json
$EDITOR shared/aws/deploy-init.json
just aws::deploy-init
just aws::deploy
just aws::publish latest
just aws::deploy-town town
just aws::deploy-rig <town-id> raspi server
just aws::deploy-device <rig-id> unit bot
```

`just aws::deploy-init` is a one-off manual step before first installation. It
reads `shared/aws/deploy-init.json` and stores the office/admin deploy parameters
as separate SSM Parameter Store parameters:

- `/txing/stack/CognitoDomainPrefix`
- `/txing/stack/AdminEmail`
- `/txing/stack/WebAppUrl`

After that, CloudFormation reads those SSM parameters directly. Each stack also
publishes its operational values under `/txing/stack/...`, for example Lambda
function ARNs, Cognito IDs, IoT policy names, and cloud MCU queue URLs. Other
stacks and `just` actions read those values from Parameter Store instead of
calling `describe-stacks` for outputs. `aws::deploy` can run without the JSON
file or any repository config file present on disk, as long as `TXING_AWS_STACK`
is provided in the environment or as a positional stack prefix.

`just aws::deploy` deploys all CloudFormation-managed AWS stacks in dependency
order:

1. `just aws::clean-stack::deploy`
2. `just aws::deploy-base`
3. `just witness::deploy`
4. `just cloud-mcu::deploy`
5. `just aws::enlist-lambda::deploy`
6. `just aws::publish-release-lambda::deploy`

`just aws::deploy-base` only deploys the base stack named
`<TXING_AWS_STACK>-aws-base`. The base stack owns Cognito for web authentication,
common IoT policies, Fleet Indexing, shared rig/device runtime IAM, shared AWS
IoT ThingTypes, and the base SSM type catalog. It does not own Lambda functions
or cloud MCU runtime infrastructure.

Standalone Lambda stacks are named from the same environment prefix, for example
`town-witness`, `town-cloud-mcu`, and `town-aws-publish-release`. `just
cloud-mcu::deploy` deploys the cloud MCU type catalog entry, SQS tick queues,
IPv6-only ECS task network, ECS task definition, and the cloud MCU/cloud rig
runtime Lambdas. Runtime Lambda deploy recipes create the shared artifact bucket
and seed a placeholder `current/bootstrap.zip` object when the release artifact
has not been published yet.

The only coupling between standalone stacks is the required `/txing/stack/...`
parameter values. The clean-stack Lambda stack publishes
`/txing/stack/AwsCleanStackFunctionArn`; the base and cloud MCU stacks read that
parameter for custom-resource service tokens. The cloud MCU stack publishes
`/txing/stack/CloudMcuTickQueueUrl` and `CloudMcuTickQueueArn`; the cloud rig
stack reads those parameters for SQS access.

`just aws::publish latest` invokes the AWS-hosted publisher Lambda, which
downloads public GitHub release assets, uploads runtime Lambda artifacts, and
updates existing runtime Lambda functions. Run it after the `Txing Release`
workflow and after the standalone Lambda stacks exist.
The publisher receives its target Lambda names from `/txing/stack/...`
parameters created by the runtime Lambda stacks.

`just aws::publish-lambda latest` runs the same runtime Lambda publish code
locally and remains available for manual repair or one-off publishing, but stack
creation no longer depends on it.

Resource names are deterministic from `TXING_AWS_STACK` where AWS exposes a physical name.
Web hosting is externalized to Cloudflare Pages. The type catalog is
CloudFormation-managed under `/txing` as leaf parameters such as
`/txing/town/cloud/cloud-mcu/kind` and
`/txing/town/cloud/cloud-mcu/capabilities`.

`just aws::deploy-town <town-name>` idempotently creates or updates only the
town thing with ThingType `town` and its `sparkplug` shadow. It prints the
generated town thing ID.

`just aws::deploy-rig <town-id> <rig-type> <rig-name>` idempotently creates or
updates only the rig thing with ThingType `raspi` or `cloud` plus the rig
`sparkplug` shadow. Standalone `raspi` rig daemon IAM and IoT role-alias
resources are deployed by the environment stack; AWS-hosted `cloud` rig runtime
IAM is deployed by the same stack.

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
just office::write-env
just office::build
```

`office::write-env` is allowed to write `office/.env.local` because it is an office build
input derived from `/txing/stack/...` parameters. Production hosting is handled manually in
Cloudflare Pages:

- Project: `txing-office`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `office`
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

The environment stack reads `WebAppUrl` from `/txing/stack/WebAppUrl`.
Cognito callback URLs are:

- `https://office.txing.dev/`
- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

Cognito logout URLs are:

- `https://office.txing.dev/`
- `https://txing.dev/`
- `http://localhost:5173/`
- `http://127.0.0.1:5173/`

Production office sign-off redirects through Cognito to `https://txing.dev/`.
Local development sign-off still returns to the current local office origin.

Public `txing.dev` is a separate Cloudflare Pages project:

- Project: `txing-dev`
- Repository: `mparkachov/txing`
- Production branch: `main`
- Root directory: `www`
- Build command: `exit 0`
- Deploy command: leave empty; do not use `npx wrangler deploy`
- Build output directory: `.` when Root directory is `www`
- Domain: `txing.dev`
- Environment variables: none
- Build watch paths include: `www/*`
- Build watch paths exclude: empty

## Runtime Checks

Inspect the operational Parameter Store contract:

```bash
just aws::describe
```

`just aws::describe-all` prints stack status for each standalone stack and then
prints the `/txing/stack/...` values. It does not use stack outputs as an
automation contract.

Validate runtime access:

```bash
just rig::check <rig-id>
just unit::daemon::run
```

Production `raspi` rig services run as standalone systemd daemons. Production
`cloud` rig services run as AWS Lambda functions. Local command wrappers use
native AWS CLI configuration and live AWS resolution; they do not depend on
generated local AWS config files.

## Important Naming Rule

IAM roles, IAM managed policies, IoT role aliases, and IoT policies use
CloudFormation-generated physical names. Do not depend on old fixed names such as
`town-rig-runtime` or `town-rig-device-policy`; use `/txing/stack/...`
parameters or AWS API lookups.

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

`aws::cert` is a compatibility wrapper for `rig::cert`. It resolves the rig
thing by generated thing ID, creates a new active AWS IoT certificate, creates
or updates the rig daemon IoT role alias, attaches the certificate to the rig
thing, renders `daemon.env`, and writes material under `config/certs/rig/`.

```bash
just aws::cert <rig-id>
```

Generated files:

- `config/certs/rig/<rig-id>/rig-daemon/daemon.env`
- `config/certs/rig/<rig-id>/rig-daemon/certificate.pem.crt`
- `config/certs/rig/<rig-id>/rig-daemon/public.pem.key`
- `config/certs/rig/<rig-id>/rig-daemon/private.pem.key`
- `config/certs/rig/<rig-id>/rig-daemon/certificate.arn`
- `config/certs/rig/<rig-id>/rig-daemon/AmazonRootCA1.pem`
- `config/certs/rig/<rig-id>/<rig-id>-rig-daemon-config.tgz`

`config/certs/` is explicitly ignored by git. The recipe refuses to overwrite
existing material; move or delete the files first if you intentionally rotate the
rig certificate. On a stable `raspi` rig host, unpack the tarball under
`/root/.config/txing`. `cloud` rigs do not use this host certificate path.

## Cleanup

For a full teardown, use the ordered delete recipe:

```bash
just aws::delete
```

It deletes standalone Lambda stacks, the base stack, and the custom-resource
Lambda stack in reverse dependency order, then removes the unmanaged packaging
bucket by default. The stacks do not detach IoT policies or delete manually
enlisted IoT things; manually rolled-in resources must be handled explicitly by
the operator.

After `just aws::delete`, the expected Parameter Store state is that all
CloudFormation-owned `/txing/stack/...` operational parameters and all
`/txing/town/...` type catalog parameters are gone. The three manual
`deploy-init` inputs remain because they were created outside CloudFormation:

- `/txing/stack/CognitoDomainPrefix`
- `/txing/stack/AdminEmail`
- `/txing/stack/WebAppUrl`

To remove those final manual inputs as well:

```bash
just aws::delete-init
```

`delete-init` deletes only those three parameters and treats already-missing
parameters as a successful no-op.

Legacy AWS-hosted web stacks previously owned `WebAppBucketName` and
`WebAppDistributionId`. Current CloudFormation removes those resources because
production web hosting is on Cloudflare Pages. During the first update from an
older stack, if CloudFormation cannot delete the old web bucket because it is
not empty, manually empty only that old web bucket and retry the stack update.

CloudFormation packaging buckets are intentionally created outside the stack so
`aws cloudformation package` can upload templates before a stack exists. To
remove only the unmanaged artifact bucket after manual stack teardown:

```bash
just aws::delete-packaging-buckets
```

This removes the shared `txing-cfn-<account>-<region>-<TXING_AWS_STACK>` bucket
and the current Lambda release deployment reuses the shared `txing-cfn-*`
packaging bucket by default.

Generated IoT things and KVS signaling channels are still instance resources.
Delete those separately if you want the account back to a fully empty state.
