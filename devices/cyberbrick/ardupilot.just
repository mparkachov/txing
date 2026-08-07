# Cyberbrick-owned workflow for its disposable upstream ArduPilot checkout.
cyberbrick_dir := source_directory()
project_root := canonicalize(cyberbrick_dir + "/../..")
ardupilot_dir := project_root + "/devices/common/board/ardupilot"
ardupilot_upstream := "https://github.com/ArduPilot/ardupilot.git"
ardupilot_patch_dir := cyberbrick_dir + "/ardupilot/patches"

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
