# TBot-owned workflow for its disposable clean-upstream ArduPilot checkout.
tbot_dir := source_directory()
project_root := canonicalize(tbot_dir + "/../..")
ardupilot_dir := project_root + "/devices/common/board/ardupilot"
ardupilot_upstream := "https://github.com/ArduPilot/ardupilot.git"
ardupilot_patch_dir := tbot_dir + "/ardupilot/patches"
ardupilot_output_dir := project_root + "/tmp/tbot-ardupilot"
alpine_justfile := project_root + "/devices/common/board/alpine.just"
alpine_build_platform := "linux/arm64"

checkout:
    #!/bin/sh
    set -eu
    test ! -e "{{ardupilot_dir}}" || {
      echo "ArduPilot checkout already exists at {{ardupilot_dir}}; remove it manually before a TBot checkout." >&2
      exit 1
    }
    git clone --recurse-submodules --single-branch --branch master "{{ardupilot_upstream}}" "{{ardupilot_dir}}"

patch:
    #!/bin/sh
    set -eu
    cd "{{ardupilot_dir}}"
    test -z "$(git status --porcelain)" || {
      echo "ArduPilot checkout must be clean before applying the TBot patch stack." >&2
      exit 1
    }
    git apply --check "{{ardupilot_patch_dir}}/0001-linux-tbot-sysfs-pwm.patch"
    git apply "{{ardupilot_patch_dir}}/0001-linux-tbot-sysfs-pwm.patch"

test:
    #!/bin/sh
    set -eu

    image="$(just --quiet --justfile "{{alpine_justfile}}" image)"

    container run --progress none --memory 6g --rm -i \
      --platform "{{alpine_build_platform}}" \
      --mount "type=bind,source={{ardupilot_dir}},target=/ardupilot" \
      --mount "type=bind,source={{tbot_dir}},target=/tbot,readonly" \
      -w /ardupilot \
      "$image" \
      sh -se <<'ALPINE_TEST'
    set -eu

    test "$(uname -m)" = "aarch64"

    apk add --no-cache ca-certificates
    grep -Fx 'LOG_BACKEND_TYPE 0' /tbot/ardupilot/defaults.parm
    grep -Fx 'LOG_BACKEND_TYPE 1' /tbot/ardupilot/diagnostic.parm
    grep -Fx 'LOG_BITMASK 65535' /tbot/ardupilot/diagnostic.parm
    grep -Fx 'LOG_DISARMED 1' /tbot/ardupilot/diagnostic.parm
    ./Tools/environment_install/install-prereqs-alpine.sh
    # The bind mount preserves the host checkout's ownership.
    git config --global --add safe.directory /ardupilot
    git config --global --add safe.directory '/ardupilot/*'
    ./waf configure --board linux --extra-hwdef /tbot/ardupilot/hwdef.dat --define CANARD_64_BIT=1
    ./waf build --targets tests/test_rcoutput_sysfs_brushed
    ./build/linux/tests/test_rcoutput_sysfs_brushed
    ALPINE_TEST

build:
    #!/bin/sh
    set -eu

    image="$(just --quiet --justfile "{{alpine_justfile}}" image)"

    install -d "{{ardupilot_output_dir}}"
    container run --progress none --memory 6g --rm -i \
      --platform "{{alpine_build_platform}}" \
      --mount "type=bind,source={{ardupilot_dir}},target=/ardupilot" \
      --mount "type=bind,source={{tbot_dir}},target=/tbot,readonly" \
      --mount "type=bind,source={{ardupilot_output_dir}},target=/out" \
      -w /ardupilot \
      "$image" \
      sh -se <<'ALPINE_BUILD'
    set -eu

    test "$(uname -m)" = "aarch64"

    apk add --no-cache ca-certificates
    ./Tools/environment_install/install-prereqs-alpine.sh
    # The bind mount preserves the host checkout's ownership.
    git config --global --add safe.directory /ardupilot
    git config --global --add safe.directory '/ardupilot/*'
    ./waf configure --board linux --extra-hwdef /tbot/ardupilot/hwdef.dat --static --define CANARD_64_BIT=1
    ./waf rover
    install -m 755 build/linux/bin/ardurover /out/txing-tbot-ardupilot
    install -m 644 /tbot/ardupilot/defaults.parm /out/txing-tbot-ardupilot.defaults.parm
    install -m 644 /tbot/ardupilot/diagnostic.parm /out/txing-tbot-ardupilot.diagnostic.parm
    ALPINE_BUILD
