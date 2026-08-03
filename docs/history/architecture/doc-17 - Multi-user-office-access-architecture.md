---
id: doc-17
title: Multi-user office access architecture
type: specification
created_date: '2026-06-15 09:05'
updated_date: '2026-06-15 10:20'
---
# Multi-user office access architecture

## Goal

Allow every user who is manually enrolled in the configured Cognito User Pool to use the office application with the same existing operator/admin AWS permissions.

## Implemented State

The office SPA uses Cognito Hosted UI sign-in, exchanges the Cognito User Pool ID token through the Cognito Identity Pool, and uses the authenticated Identity Pool role for direct AWS IoT and KVS WebRTC viewer operations.

Cognito User Pool membership is the office access boundary. Office no longer compares the signed-in token email to `VITE_ADMIN_EMAIL`, and `VITE_ADMIN_EMAIL` is no longer required by runtime config, generated local env, examples, or Cloudflare environment documentation.

AWS still has an `AdminEmail` deploy-init value and a `just aws::create-admin-user` helper. That helper is a bootstrap convenience for creating a seed Cognito user, not an authorization boundary for office users.

## Behavior

Any authenticated user from the configured pool can enter office and receives the same AWS permissions through the existing Identity Pool authenticated role.

There are no Cognito groups, custom claims, per-user policies, device-specific restrictions, or in-office user-management UI in this milestone. Operators add users through the AWS Cognito console using the existing user pool and standard Cognito Hosted UI flow.

The office app continues to rely on current device and capability contracts for bot management and video visibility. Video access remains governed by the existing KVS viewer permissions and the unit device `video` capability state.

## Implementation Impact

The office email allow-list gate was removed, and office no longer requires `VITE_ADMIN_EMAIL` in runtime configuration, generated local env, examples, or Cloudflare environment documentation.

The AWS Cognito User Pool, User Pool Client, Identity Pool, Identity Pool authenticated role, and runtime IoT/KVS permissions remain unchanged. `AdminEmail`, `WebExpectedAdminEmail`, and `create-admin-user` remain as seed-admin bootstrap surfaces unless a future milestone removes that deploy-init concept entirely.

Docs and tests now describe and enforce the access model: all enrolled Cognito users can use office; `AdminEmail` is not an office allow-list.

## Risks and Non-goals

This intentionally broadens office access to every enrolled Cognito user. The operational safety boundary is user enrollment in Cognito, so operators must avoid adding untrusted users to the pool.

This milestone does not add role separation, read-only users, invite flows, self-service signup, Cognito groups, device scoping, or an office user-management screen.

## Validation

Validation for the completed milestone includes office source tests, office production build, and shared AWS Python tests covering template, versioning, and docs expectations. Manual rollout requires rebuilding/redeploying office through Cloudflare Pages and adding users in the existing Cognito User Pool.
