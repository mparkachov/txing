set shell := ["sh", "-eu", "-c"]

# Resolve the current Alpine image once so each build uses a single ARM64 manifest.
@image:
    #!/bin/sh
    set -eu
    repo=docker.io/library/alpine
    container image pull --platform linux/arm64 --progress none "$repo:latest" >&2
    digest="$(container image inspect "$repo:latest" | jq -er '
      .[0].variants[]
      | select(.platform.os == "linux" and .platform.architecture == "arm64")
      | .digest
      | select(test("^sha256:[0-9a-f]{64}$"))
    ')"
    image="$repo@$digest"
    alpine_release="$(container run --rm --progress none --platform linux/arm64 "$image" cat /etc/alpine-release)"
    case "$alpine_release" in
      3.24.*) ;;
      *) echo "Alpine latest is $alpine_release. Board artifacts require v3.24." >&2; exit 1 ;;
    esac
    printf 'Using Alpine %s (%s)\n' "$alpine_release" "$image" >&2
    printf '%s\n' "$image"
