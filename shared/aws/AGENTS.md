# shared AWS guide

## Scope

- This directory contains shared AWS CLI helpers, CloudFormation templates,
  registry utilities, and admin Lambda packaging.

## Rules

- Follow the repository-level workflow in `../../AGENTS.md`.
- Read `../../docs/constraints/repository-rules.md` before changing AWS,
  CloudFormation, SSM, IoT, release publishing, certificate, or cleanup
  behavior.
- Read `../../docs/aws-lambda-boundary.md` before changing Lambda language,
  packaging, deployment, or release boundaries.
- Do not run AWS commands that create, update, or delete resources unless the
  user explicitly asks for that operation. Read-only inspection is allowed when
  needed.
- Admin Lambdas in this tree remain Python and are packaged by `just
  aws::deploy` as CloudFormation-managed stack code.
- Do not add rollback, migration, legacy service-token bridge, or cleanup logic
  that mutates manually rolled-in resources.
- Do not depend on fixed physical names for IAM roles, IAM managed policies, IoT
  role aliases, or IoT policies; use `/txing/stack/...` parameters or AWS API
  lookups.
