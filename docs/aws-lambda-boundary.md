# AWS Lambda Language Boundary

AWS Lambda functions in this repository are split by whether they are control
plane administration or runtime data plane.

Admin Lambdas are Python. Their deployed function names are prefixed with the
environment stack name, for example `town-aws-publish-release`:

- `aws-publish-release`
- `aws-enlist-txing`
- `aws-clean-stack`

These functions call boto3-heavy AWS control-plane APIs for CloudFormation, S3,
IoT registry, SSM, and operator publishing workflows. They are
packaged by `just aws::deploy` as CloudFormation-managed stack code, not as
GitHub release runtime artifacts. Each Lambda is owned by a standalone template
under `shared/aws/lambdas/`.
The template is intentionally clean-stack only: it does not contain rollback,
migration, or legacy service-token bridge modes.
Admin Lambda code is packaged as current content-addressed stack code, not as a
semver-managed release artifact.

Existing shared runtime Lambdas are Go. GitHub release assets and S3 object keys
keep these stable artifact ids, while deployed function names are prefixed with the
environment stack name and omit the redundant `-lambda` suffix, for example
`town-cloud-rig`:

- `txing-witness-lambda`
- `txing-cloud-rig-lambda`
- `txing-cloud-mcu-lambda`

These functions stay as static `linux/arm64` `bootstrap` executables for
`provided.al2023`. They are published as release artifacts and updated by
`release::publish lambda`.

Milestone 10 introduces one explicit C++ exception: the agent controller,
`txing-agent-lambda`, under the top-level agent component. It uses the AWS SDK
for C++ and a C++ custom Lambda runtime packaged for Linux ARM64 on
`provided.al2023`. It does not inherit the Go-only/static-bootstrap build
assumption above. Package and validate its native dependencies with its
release artifact.

The agent application itself is a native C++ executable on macOS and Linux
ARM64, hosted in Lambda MicroVMs in cloud operation. It is not a fifteen-minute
Lambda function. Its controller remains a short-lived event function. Agent
runtime/controller publication follows the approved `agent` release and
`just agent::publish <version>` interface rather than adding a Go controller
to the shared `lambda` release stream.

This is approved replacement guidance, not completed implementation. The old
`txing-tbot-companion-lambda` Go controller and Fargate paths have been removed
from the repository; deployed-resource retirement remains a manual operator
action. The replacement C++ controller and runtime integration are in progress
under #168; prepared source does not establish deployment or live acceptance. See
[Agent](components/agent.md) and [Agent constraints](constraints/agent.md).

Firmware uses the stock Zephyr C stack; standalone rig daemons and the existing
shared runtime Lambdas remain Go. Existing admin Python functions are unchanged.
Agent runtime, controller and publication code remain subject to the C++
implementation boundary.
The 2026-10-29 operator amendment adds one narrow exception: the independent
stop-only [agent watch](constraints/agent-watch.md) runs in the existing Go
witness function. It does not implement agent startup, assignment, shadow
publication, device sessions, or the C++ controller's ordinary workflow.

Within this repository, deploy actions are CloudFormation-backed AWS stack
updates. Publish actions promote already-built release artifacts to existing
runtime targets.
