# Cyberbrick-owned workflow for its disposable upstream ArduPilot checkout.
cyberbrick_dir := source_directory()
project_root := canonicalize(cyberbrick_dir + "/../..")
ardupilot_dir := project_root + "/devices/common/board/ardupilot"
ardupilot_upstream := "https://github.com/ArduPilot/ardupilot.git"
ardupilot_patch_dir := cyberbrick_dir + "/ardupilot/patches"
ardupilot_output_dir := project_root + "/tmp/cyberbrick-ardupilot"
alpine_build_image := "docker.io/library/alpine:3.24.1"
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

    command -v nerdctl >/dev/null 2>&1 || {
      echo "nerdctl is required to build Cyberbrick ArduPilot in Alpine." >&2
      exit 1
    }
    server_platform="$(nerdctl info --format '{{"{{"}}.OSType{{"}}"}}/{{"{{"}}.Architecture{{"}}"}}')"
    case "$server_platform" in
      linux/aarch64|linux/arm64) ;;
      *)
        echo "Cyberbrick ArduPilot builds require a native linux/arm64 nerdctl environment, got: $server_platform" >&2
        exit 1
        ;;
    esac

    install -d "{{ardupilot_output_dir}}"
    nerdctl run --rm -i \
      --platform "{{alpine_build_platform}}" \
      --mount "type=bind,source={{ardupilot_dir}},target=/ardupilot" \
      --mount "type=bind,source={{cyberbrick_dir}},target=/cyberbrick,readonly" \
      --mount "type=bind,source={{ardupilot_output_dir}},target=/out" \
      -w /ardupilot \
      "{{alpine_build_image}}" \
      sh -se <<'ALPINE_BUILD'
    set -eu

    test "$(cat /etc/alpine-release)" = "3.24.1"
    test "$(uname -m)" = "aarch64"

    apk add --no-cache ca-certificates
    ./Tools/environment_install/install-prereqs-alpine.sh
    ./waf configure --board linux --extra-hwdef /cyberbrick/ardupilot/hwdef.dat --static --define CANARD_64_BIT=1
    ./waf rover
    install -m 755 build/linux/bin/ardurover /out/txing-cyberbrick-ardupilot
    install -m 644 /cyberbrick/ardupilot/defaults.parm /out/txing-cyberbrick-ardupilot.defaults.parm
    ALPINE_BUILD
