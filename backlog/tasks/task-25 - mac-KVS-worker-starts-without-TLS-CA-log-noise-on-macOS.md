---
id: TASK-25
title: mac KVS worker starts without TLS CA log noise on macOS
status: To Do
assignee: []
created_date: '2026-07-05 15:30'
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
- [ ] #1 Starting the worker on macOS logs no TLS CA parse error, and TLS verification against AWS KVS endpoints still succeeds end to end.
- [ ] #2 The macOS CA anchor matches the Linux lane's Starfield root with a documented fallback, and Linux build behavior is unchanged.
<!-- AC:END -->
