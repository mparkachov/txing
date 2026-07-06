---
id: TASK-25
title: mac KVS worker starts without TLS CA log noise on macOS
status: Done
assignee:
  - '@claude'
created_date: '2026-07-05 15:30'
updated_date: '2026-07-06 04:31'
labels: []
milestone: m-1
dependencies: []
references:
  - devices/mac/justfile
  - devices/unit/board/kvs_master/CMakeLists.txt
  - devices/unit/board/kvs_master/src/kvs_session_real.cpp
priority: low
ordinal: 62000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On macOS the worker is built with TXING_KVS_SYSTEM_CA_CERT_PATH=/etc/ssl/cert.pem (the full multi-certificate PEM bundle) because macOS has no per-CA split files. libwebsockets attempts a DER parse of that bundle while creating the client TLS context and logs 'E: lws_tls_client_create_vhost_context: d2i_X509 failed' once at startup before succeeding with the PEM fallback; TLS verification against AWS demonstrably works (signaling describe/token calls succeed and video streams). The Linux lane avoids this by pointing at a single Starfield Services Root Certificate Authority - G2 PEM. Proposed fix: have just mac::kvs-build extract that same Starfield root from the macOS system root store (security find-certificate -c 'Starfield Services Root Certificate Authority - G2' -p /System/Library/Keychains/SystemRootCertificates.keychain) into the build directory and bake that path in, keeping the bundle as fallback when extraction fails. Related accepted noise not in scope: Homebrew libwebsockets ships demo plugins (sshd demo, raw-test, deaddrop) that log warnings at context init; silencing them would require a leaner lws build.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Starting the worker on macOS logs no TLS CA parse error, and TLS verification against AWS KVS endpoints still succeeds end to end.
- [x] #2 The macOS CA anchor matches the Linux lane's Starfield root with a documented fallback, and Linux build behavior is unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. just mac::kvs-build: when TXING_BOARD_KVS_SYSTEM_CA_CERT_PATH is not set, extract the Starfield Services Root Certificate Authority - G2 PEM from the macOS system root store (security find-certificate -p) into the build directory and pass that file as TXING_KVS_SYSTEM_CA_CERT_PATH; fall back to /etc/ssl/cert.pem when extraction fails; env override keeps precedence. Linux lane untouched.
2. Document the CA anchor and fallback in the mac README video section.
3. Validate: rebuild, restart the supervised worker (daemon spawns the new binary), confirm the worker log has no d2i_X509 error and signaling/streaming still succeed (TXING_KVS_READY).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
just mac::kvs-build now anchors TXING_KVS_SYSTEM_CA_CERT_PATH to a Starfield Services Root Certificate Authority - G2 PEM extracted from the macOS system root store (security find-certificate) into build-macos/starfield-services-root-g2.pem - the same root the Linux lane pins from /etc/ssl/certs. Verified: extraction yields exactly one certificate with the published SHA-256 fingerprint 568D6905A2C88708A4B3025190EDCFEDB1974A606A13C6E5290FCB2AE63EDAB5, and the rebuilt worker bakes the extracted path (strings check). TXING_BOARD_KVS_SYSTEM_CA_CERT_PATH still overrides; extraction failure falls back to /etc/ssl/cert.pem with a stderr note; README documents anchor, fallback, and override. Linux lane untouched (change confined to devices/mac/justfile and the mac README). Live start check (no d2i_X509 line, signaling succeeds) pending: stack currently stopped and daemon start must come from the user's terminal for camera TCC.

Live validation 2026-07-06 04:30Z on mac-rcg3rg: the user brought the stack up and commanded REDCON 1; the supervised worker (0.15.4, built with the Starfield anchor) started with zero d2i_X509 lines in its run window, connected signaling (172ms), and emitted TXING_KVS_READY - TLS verification against AWS KVS succeeds end to end with the single extracted root.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The macOS KVS worker starts without TLS CA log noise. just mac::kvs-build extracts the Starfield Services Root Certificate Authority - G2 PEM (the same root the Linux lane pins, fingerprint-verified) from the macOS system root store into the build directory and bakes it as TXING_KVS_SYSTEM_CA_CERT_PATH, so libwebsockets no longer attempts a DER parse of the multi-certificate /etc/ssl/cert.pem bundle. TXING_BOARD_KVS_SYSTEM_CA_CERT_PATH overrides the anchor; failed extraction falls back to the bundle with a stderr note; README documents anchor, fallback, and override. Linux build behavior unchanged (change confined to devices/mac/justfile and the mac README). Validated live: worker startup with zero d2i_X509 lines, signaling connected, TXING_KVS_READY emitted. Remaining accepted noise: Homebrew libwebsockets demo-plugin warnings at context init. Rollout: dev-only, just mac::kvs-build (already built); the daemon spawns the anchored binary automatically.
<!-- SECTION:FINAL_SUMMARY:END -->
