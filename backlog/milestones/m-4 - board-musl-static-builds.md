---
id: m-4
title: "board musl static builds"
---

## Description

Complete the migration of board component builds off Debian: all unit and cyberbrick board binaries are built in the single pinned Alpine/musl toolchain instead of debian:trixie with Raspberry Pi apt repositories, statically linked wherever possible so the shipped daemon and hardware worker run unmodified on both existing Debian boards and Alpine boards. The camera KVS master cannot be linked statically and stays dynamically linked against musl and stock Alpine libcamera, making new camera builds Alpine-only; Debian boards keep the last Debian-built KVS master until reimaged to Alpine.
