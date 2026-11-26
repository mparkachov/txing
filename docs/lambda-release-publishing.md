# Automatic publishing for runtime Lambda releases

Accepted design. See [Artifacts](artifacts.md#lambda-artifacts) for the current
publishing procedure.

## Release flow

The existing `Release lambda` workflow builds the Witness, cloud rig, cloud MCU,
and virtual-quad controller packages and publishes them as `lambda-vX.Y.Z`.
After that release is public, a dependent job sends a synchronous `POST` to the
URL in the GitHub Actions repository variable `LAMBDA_PUBLISH_URL` with the
tag from the publish job. The workflow validates that the variable is present
before publishing the release. A failed AWS publish can be retried by rerunning
the failed job from the same run while that release is current.

The Function URL belongs to the existing `aws-publish-release` admin Lambda. Its
CloudFormation stack exposes the URL as `ReleasePublisherFunctionUrl`. Set
`AuthType: NONE` and grant both public invocation permissions, with
`lambda:InvokeFunction` restricted to requests through that Function URL. The
publisher keeps its existing IAM scope for the configured runtime functions and
artifact bucket. GitHub Actions uses HTTPS for the invocation and needs no AWS
credentials or OIDC connection. [AWS Function URL permissions](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html)

## Publishing and completion

`POST /` accepts a JSON body such as `{"release":"lambda-v1.2.3"}`. AWS resolves
`latest` in the configured repository's `lambda-v*` release stream and compares
it with the requested tag before writing any artifacts or updating functions.
If the tags differ, the endpoint returns a conflict. Anyone with the URL can
trigger a publish of the current release and consume AWS and GitHub request
capacity. The existing IAM-authenticated `just release::publish lambda [release]`
command still supports explicit release references for manual recovery.

The publisher reuses its public GitHub downloads, package validation, S3
artifact keys, and `UpdateFunctionCode` calls. It updates each runtime function's
`$LATEST` code and waits for AWS to finish applying each update. The waiter checks
the code update status. The flow leaves running invocations alone and relies on
Lambda to use the new code for subsequent invocations after the update. [Lambda function states during updates](https://docs.aws.amazon.com/lambda/latest/dg/functions-states.html)

The HTTP request returns success after all four code updates succeed. The workflow
checks the returned release tag against the tag created by its publish job and
fails on a timeout, an HTTP error, or a mismatched tag. A failure can leave a
partial rollout if AWS has already updated some functions. The workflow has no
new locks, deploy queue, alias management, or invocation monitoring. Agent
publication continues through its separate release stream.

## Rollout and verification

1. An operator updates the AWS admin stack using `just aws::deploy` and copies
   its `ReleasePublisherFunctionUrl` output into the `LAMBDA_PUBLISH_URL`
   repository variable.
2. Validate the handler, Function URL policy, and workflow locally. Cover rejected
   HTTP methods and inputs, a stale release tag, a missing target function, an
   AWS update failure, a mismatched returned release tag, and the existing direct
   invocation path.
3. Bump `release/versions/lambda` for a new release and run `Release lambda`.
   Verify that the workflow succeeds only after all four functions have the
   released code and that subsequent invocations use it.
