# Cyberbrick-owned workflow for its disposable upstream ArduPilot checkout.
cyberbrick_dir := source_directory()
project_root := canonicalize(cyberbrick_dir + "/../..")
ardupilot_dir := project_root + "/devices/common/board/ardupilot"
ardupilot_upstream := "https://github.com/ArduPilot/ardupilot.git"
ardupilot_patch_dir := cyberbrick_dir + "/ardupilot/patches"
ardupilot_output_dir := project_root + "/tmp/cyberbrick-ardupilot"
alpine_justfile := project_root + "/devices/common/board/alpine.just"
alpine_build_platform := "linux/arm64"

checkout:
    #!/bin/sh
    set -eu
    git clone --recurse-submodules --single-branch --branch master "{{ardupilot_upstream}}" "{{ardupilot_dir}}"

patch:
    #!/bin/sh
    set -eu
    cd "{{ardupilot_dir}}"
    git apply \
      "{{ardupilot_patch_dir}}/0001-linux-sysfs-pwm-subtype.patch" \
      "{{ardupilot_patch_dir}}/0002-linux-sysfs-pwm-no-imu.patch"

build:
    #!/bin/sh
    set -eu

    image="$(just --quiet --justfile "{{alpine_justfile}}" image)"

    install -d "{{ardupilot_output_dir}}"
    container run --progress none --memory 6g --rm -i \
      --platform "{{alpine_build_platform}}" \
      --mount "type=bind,source={{ardupilot_dir}},target=/ardupilot" \
      --mount "type=bind,source={{cyberbrick_dir}},target=/cyberbrick,readonly" \
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
    ./waf configure --board linux --extra-hwdef /cyberbrick/ardupilot/hwdef.dat --static --define CANARD_64_BIT=1
    ./waf rover
    install -m 755 build/linux/bin/ardurover /out/txing-cyberbrick-ardupilot
    install -m 644 /cyberbrick/ardupilot/defaults.parm /out/txing-cyberbrick-ardupilot.defaults.parm
    ALPINE_BUILD
