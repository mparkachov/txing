---
id: doc-18
title: 'Milestone: multi-user office access'
type: guide
created_date: '2026-06-15 09:05'
updated_date: '2026-06-15 09:05'
---
# Milestone: multi-user office access

## Outcome

The office app accepts any user enrolled in the configured Cognito User Pool and gives that user the same current operator/admin office capabilities through the existing Identity Pool authenticated role.

## Scope

In scope:

- Remove the office client-side single-admin-email authorization gate.
- Stop requiring `VITE_ADMIN_EMAIL` for office runtime configuration.
- Keep existing Cognito Hosted UI, User Pool Client, Identity Pool, IoT policy attachment, direct shadow access, Sparkplug commands, MCP, and KVS WebRTC viewer flows.
- Update docs and tests so user enrollment is documented as Cognito console administration.

Out of scope:

- Cognito groups, custom claims, invite workflows, self-service signup, read-only roles, per-device restrictions, or in-office user-management screens.
- Removing the bootstrap `AdminEmail` deploy-init parameter or `just aws::create-admin-user` helper.
- Changing device, unit shadow, MCP, Sparkplug, or video contracts.

## Exit criteria

- A Cognito user whose email is not the seed admin email can sign into office and is not rejected by the SPA.
- The signed-in user can reach the configured town route, browse rigs/devices, manage a bot through existing controls, and open video when the bot video capability is available.
- Local and Cloudflare office configuration no longer needs `VITE_ADMIN_EMAIL`.
- AWS and office docs explain that `AdminEmail` is only a bootstrap seed user and that additional users are added in the Cognito console.
- Office tests/build and relevant shared AWS Python tests pass.

## Rollout

After implementation, rebuild and redeploy office through the existing Cloudflare Pages Git flow. No AWS template redeploy should be required for existing pools unless docs-only CloudFormation wording changes are included in a normal stack update. Operators add additional users directly in the configured Cognito User Pool.
