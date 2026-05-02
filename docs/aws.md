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
just aws::town-deploy town
just aws::rig-deploy <town-id> raspi server
just aws::device-deploy <rig-id> unit bot
```

`just aws::deploy` deploys the base root stack and nested base template. It owns
web/Cognito infrastructure, common IoT policies, common artifact buckets, and the
Sparkplug witness Lambda/topic rule. It also configures AWS IoT fleet indexing
through the AWS IoT API after the stack deploy, then syncs the hardcoded SSM
type catalog under `/txing` as separate leaf parameters such as
`/txing/town/cloud/time/kind` and `/txing/town/cloud/time/capabilities`.

`just aws::town-deploy <town-name>` deploys the town layer and idempotently
ensures the town thing, town thing type/group, and town `sparkplug` shadow. It
prints the generated town thing ID.

`just aws::rig-deploy <town-id> <rig-type> <rig-name>` deploys the rig layer and
idempotently ensures the rig thing, its `rigType` registry attribute, rig
dynamic group, rig `sparkplug` shadow, Greengrass token exchange role alias, and
rig runtime IAM.

`just aws::device-deploy <rig-id> <device-type> <device-name>` deploys the
device layer and idempotently ensures the device thing, device type, rig
enrollment attributes, named shadows, and optional resources. Device enrollment
validates compatibility by requiring the SSM leaf
`/txing/town/<rigType>/<deviceType>/kind`. Instance data stays in AWS IoT thing
attributes, not SSM.

## Web Admin

Create or update the Cognito admin user after `aws::deploy`:

```bash
just aws::create-admin-user '<strong-password>'
```

Generate and publish the SPA:

```bash
just web::write-env
just web::build
just web::publish
```

`web::write-env` is allowed to write `web/.env.local` because it is a web build
input derived from live stack outputs.

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
rig certificate. `just rig::install-service` installs the generated certificate
and private key into `/var/lib/greengrass/credentials` and installs Amazon Root
CA 1 for Greengrass.

## Cleanup

For a full teardown, delete resources in reverse dependency order:

```bash
just aws-town cloudformation delete-stack --stack-name "$TXING_DEVICE_STACK_NAME"
just aws-town cloudformation delete-stack --stack-name "$TXING_RIG_STACK_NAME"
just aws-town cloudformation delete-stack --stack-name "$TXING_TOWN_STACK_NAME"
just aws-town cloudformation delete-stack --stack-name "$AWS_STACK_NAME"
```

The base stack has delete-time cleanup custom resources for disposable S3 bucket
contents and IoT policy attachments created outside CloudFormation, such as rig
certificates and browser Cognito identities. You should not need to manually
empty `WebAppBucketName` or `GreengrassArtifactsBucketName`, and the base IoT
policies should be detached from their principals before CloudFormation deletes
the policy resources.

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

Generated IoT things, dynamic thing groups, KVS signaling channels, and
deprecated thing types are still instance resources. Delete those separately if
you want the account back to a fully empty state.
