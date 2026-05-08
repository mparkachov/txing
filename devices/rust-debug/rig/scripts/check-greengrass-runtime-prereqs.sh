#!/usr/bin/env bash
set -euo pipefail

missing=0

if [ -z "${AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT:-}" ]; then
  echo "Missing AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT." >&2
  missing=1
elif [ ! -S "${AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT}" ] && [ ! -e "${AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT}" ]; then
  echo "Greengrass IPC socket does not exist: ${AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT}" >&2
  missing=1
fi

if [ -z "${SVCUID:-}" ]; then
  echo "Missing SVCUID." >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo "The real component command must run under a Greengrass component lifecycle." >&2
  echo "For local SDK-free development, run: just rust-debug::rig::mock-component" >&2
  exit 1
fi
