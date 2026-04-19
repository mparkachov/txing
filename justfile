set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

root_dir := source_directory()

[private]
_project-aws-env scope='rig' region='' profile='' stack_name='' cognito_domain_prefix='' admin_email='' aws_shared_credentials_file='' aws_config_file='' env_file='' rig_env_file='' board_env_file='':
    #!/usr/bin/env bash
    set -euo pipefail

    project_root="{{root_dir}}"

    resolve_path() {
      local candidate="$1"
      if [ -z "$candidate" ]; then
        return 0
      fi
      case "$candidate" in
        /*) printf '%s\n' "$candidate" ;;
        *) printf '%s\n' "$project_root/$candidate" ;;
      esac
    }

    choose_value() {
      local explicit="$1"
      local fallback="$2"
      if [ -n "$explicit" ]; then
        printf '%s\n' "$explicit"
      else
        printf '%s\n' "$fallback"
      fi
    }

    export_line() {
      local name="$1"
      local value="$2"
      printf 'export %s=%q\n' "$name" "$value"
    }

    env_file="$(resolve_path "$(choose_value "{{env_file}}" "config/aws.env")")"
    if [ -f "$env_file" ]; then
      # shellcheck disable=SC1090
      source "$env_file"
    fi

    rig_env_file=""
    if [ "{{scope}}" = "rig" ]; then
      rig_env_file="$(resolve_path "$(choose_value "{{rig_env_file}}" "${RIG_ENV_FILE:-config/rig.env}")")"
      if [ -f "$rig_env_file" ]; then
        # shellcheck disable=SC1090
        source "$rig_env_file"
      fi
    fi

    board_env_file=""
    if [ "{{scope}}" = "device" ]; then
      board_env_file="$(resolve_path "$(choose_value "{{board_env_file}}" "${BOARD_ENV_FILE:-config/board.env}")")"
      if [ -f "$board_env_file" ]; then
        # shellcheck disable=SC1090
        source "$board_env_file"
      fi
    fi

    aws_town_profile_default="${AWS_TOWN_PROFILE:-town}"
    aws_rig_profile_default="${AWS_RIG_PROFILE:-rig}"
    aws_device_profile_default="${AWS_DEVICE_PROFILE:-device}"
    aws_selected_profile_default="$aws_rig_profile_default"
    if [ "{{scope}}" = "town" ]; then
      aws_selected_profile_default="$aws_town_profile_default"
    elif [ "{{scope}}" = "device" ]; then
      aws_selected_profile_default="$aws_device_profile_default"
    fi

    aws_region="$(choose_value "{{region}}" "${AWS_REGION:-eu-central-1}")"
    aws_stack_name="$(choose_value "{{stack_name}}" "${AWS_STACK_NAME:-txing-iot}")"
    aws_cognito_domain_prefix="$(choose_value "{{cognito_domain_prefix}}" "${AWS_COGNITO_DOMAIN_PREFIX:-txing-iot}")"
    aws_admin_email="$(choose_value "{{admin_email}}" "${AWS_ADMIN_EMAIL:-admin@example.com}")"
    aws_town_profile="$aws_town_profile_default"
    aws_rig_profile="$aws_rig_profile_default"
    aws_selected_profile="$(choose_value "{{profile}}" "$aws_selected_profile_default")"
    aws_shared_credentials_file="$(resolve_path "$(choose_value "{{aws_shared_credentials_file}}" "${AWS_SHARED_CREDENTIALS_FILE:-config/aws.credentials}")")"
    aws_config_file="$(resolve_path "$(choose_value "{{aws_config_file}}" "${AWS_CONFIG_FILE:-config/aws.config}")")"
    rig_name="${RIG_NAME:-rig}"
    sparkplug_group_id="${SPARKPLUG_GROUP_ID:-town}"
    sparkplug_edge_node_id="${SPARKPLUG_EDGE_NODE_ID:-rig}"
    cloudwatch_log_group="${CLOUDWATCH_LOG_GROUP:-/town/rig/txing}"
    thing_name="${THING_NAME:-unit-local}"
    schema_file="$(resolve_path "${SCHEMA_FILE:-devices/unit/aws/shadow.schema.json}")"
    board_video_viewer_url="${BOARD_VIDEO_VIEWER_URL:-}"
    board_video_region="${BOARD_VIDEO_REGION:-eu-central-1}"
    board_video_channel_name="${BOARD_VIDEO_CHANNEL_NAME:-$thing_name-board-video}"
    board_video_sender_command="${BOARD_VIDEO_SENDER_COMMAND:-}"
    kvs_dualstack_endpoints="${KVS_DUALSTACK_ENDPOINTS:-}"
    lg_wd="${LG_WD:-}"
    board_drive_raw_max_speed="${BOARD_DRIVE_RAW_MAX_SPEED:-}"
    board_drive_cmd_raw_min_speed="${BOARD_DRIVE_CMD_RAW_MIN_SPEED:-}"
    board_drive_cmd_raw_max_speed="${BOARD_DRIVE_CMD_RAW_MAX_SPEED:-}"
    board_drive_pwm_hz="${BOARD_DRIVE_PWM_HZ:-}"
    board_drive_pwm_chip="${BOARD_DRIVE_PWM_CHIP:-}"
    board_drive_left_pwm_channel="${BOARD_DRIVE_LEFT_PWM_CHANNEL:-}"
    board_drive_right_pwm_channel="${BOARD_DRIVE_RIGHT_PWM_CHANNEL:-}"
    board_drive_gpio_chip="${BOARD_DRIVE_GPIO_CHIP:-}"
    board_drive_left_dir_gpio="${BOARD_DRIVE_LEFT_DIR_GPIO:-}"
    board_drive_right_dir_gpio="${BOARD_DRIVE_RIGHT_DIR_GPIO:-}"
    board_drive_left_inverted="${BOARD_DRIVE_LEFT_INVERTED:-}"
    board_drive_right_inverted="${BOARD_DRIVE_RIGHT_INVERTED:-}"

    export_line TXING_PROJECT_ROOT "$project_root"
    export_line AWS_ENV_FILE "$env_file"
    if [ -n "$rig_env_file" ]; then
      export_line RIG_ENV_FILE "$rig_env_file"
    else
      printf 'unset RIG_ENV_FILE\n'
    fi
    if [ -n "$board_env_file" ]; then
      export_line BOARD_ENV_FILE "$board_env_file"
    else
      printf 'unset BOARD_ENV_FILE\n'
    fi
    export_line AWS_REGION "$aws_region"
    export_line AWS_STACK_NAME "$aws_stack_name"
    export_line AWS_COGNITO_DOMAIN_PREFIX "$aws_cognito_domain_prefix"
    export_line AWS_ADMIN_EMAIL "$aws_admin_email"
    export_line AWS_TOWN_PROFILE "$aws_town_profile"
    export_line AWS_RIG_PROFILE "$aws_rig_profile"
    export_line AWS_DEVICE_PROFILE "$aws_device_profile_default"
    export_line AWS_SELECTED_PROFILE "$aws_selected_profile"
    export_line AWS_SHARED_CREDENTIALS_FILE "$aws_shared_credentials_file"
    export_line AWS_CONFIG_FILE "$aws_config_file"
    export_line RIG_NAME "$rig_name"
    export_line SPARKPLUG_GROUP_ID "$sparkplug_group_id"
    export_line SPARKPLUG_EDGE_NODE_ID "$sparkplug_edge_node_id"
    export_line CLOUDWATCH_LOG_GROUP "$cloudwatch_log_group"
    export_line THING_NAME "$thing_name"
    export_line SCHEMA_FILE "$schema_file"
    export_line BOARD_VIDEO_VIEWER_URL "$board_video_viewer_url"
    export_line BOARD_VIDEO_REGION "$board_video_region"
    export_line BOARD_VIDEO_CHANNEL_NAME "$board_video_channel_name"
    export_line BOARD_VIDEO_SENDER_COMMAND "$board_video_sender_command"
    if [ -n "$kvs_dualstack_endpoints" ]; then
      export_line KVS_DUALSTACK_ENDPOINTS "$kvs_dualstack_endpoints"
    else
      printf 'unset KVS_DUALSTACK_ENDPOINTS\n'
    fi
    if [ -n "$lg_wd" ]; then
      export_line LG_WD "$lg_wd"
    else
      printf 'unset LG_WD\n'
    fi
    if [ -n "$board_drive_raw_max_speed" ]; then
      export_line BOARD_DRIVE_RAW_MAX_SPEED "$board_drive_raw_max_speed"
    else
      printf 'unset BOARD_DRIVE_RAW_MAX_SPEED\n'
    fi
    if [ -n "$board_drive_cmd_raw_min_speed" ]; then
      export_line BOARD_DRIVE_CMD_RAW_MIN_SPEED "$board_drive_cmd_raw_min_speed"
    else
      printf 'unset BOARD_DRIVE_CMD_RAW_MIN_SPEED\n'
    fi
    if [ -n "$board_drive_cmd_raw_max_speed" ]; then
      export_line BOARD_DRIVE_CMD_RAW_MAX_SPEED "$board_drive_cmd_raw_max_speed"
    else
      printf 'unset BOARD_DRIVE_CMD_RAW_MAX_SPEED\n'
    fi
    if [ -n "$board_drive_pwm_hz" ]; then
      export_line BOARD_DRIVE_PWM_HZ "$board_drive_pwm_hz"
    else
      printf 'unset BOARD_DRIVE_PWM_HZ\n'
    fi
    if [ -n "$board_drive_pwm_chip" ]; then
      export_line BOARD_DRIVE_PWM_CHIP "$board_drive_pwm_chip"
    else
      printf 'unset BOARD_DRIVE_PWM_CHIP\n'
    fi
    if [ -n "$board_drive_left_pwm_channel" ]; then
      export_line BOARD_DRIVE_LEFT_PWM_CHANNEL "$board_drive_left_pwm_channel"
    else
      printf 'unset BOARD_DRIVE_LEFT_PWM_CHANNEL\n'
    fi
    if [ -n "$board_drive_right_pwm_channel" ]; then
      export_line BOARD_DRIVE_RIGHT_PWM_CHANNEL "$board_drive_right_pwm_channel"
    else
      printf 'unset BOARD_DRIVE_RIGHT_PWM_CHANNEL\n'
    fi
    if [ -n "$board_drive_gpio_chip" ]; then
      export_line BOARD_DRIVE_GPIO_CHIP "$board_drive_gpio_chip"
    else
      printf 'unset BOARD_DRIVE_GPIO_CHIP\n'
    fi
    if [ -n "$board_drive_left_dir_gpio" ]; then
      export_line BOARD_DRIVE_LEFT_DIR_GPIO "$board_drive_left_dir_gpio"
    else
      printf 'unset BOARD_DRIVE_LEFT_DIR_GPIO\n'
    fi
    if [ -n "$board_drive_right_dir_gpio" ]; then
      export_line BOARD_DRIVE_RIGHT_DIR_GPIO "$board_drive_right_dir_gpio"
    else
      printf 'unset BOARD_DRIVE_RIGHT_DIR_GPIO\n'
    fi
    if [ -n "$board_drive_left_inverted" ]; then
      export_line BOARD_DRIVE_LEFT_INVERTED "$board_drive_left_inverted"
    else
      printf 'unset BOARD_DRIVE_LEFT_INVERTED\n'
    fi
    if [ -n "$board_drive_right_inverted" ]; then
      export_line BOARD_DRIVE_RIGHT_INVERTED "$board_drive_right_inverted"
    else
      printf 'unset BOARD_DRIVE_RIGHT_INVERTED\n'
    fi
    export_line AWS_DEFAULT_REGION "$aws_region"
    if [ -n "$aws_selected_profile" ]; then
      export_line AWS_PROFILE "$aws_selected_profile"
      export_line AWS_DEFAULT_PROFILE "$aws_selected_profile"
    else
      printf 'unset AWS_PROFILE\n'
      printf 'unset AWS_DEFAULT_PROFILE\n'
    fi

[positional-arguments]
@aws-rig *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{root_dir}}/justfile" _project-aws-env rig)"
    command aws "$@"

[positional-arguments]
@aws-town *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{root_dir}}/justfile" _project-aws-env town)"
    command aws "$@"

[positional-arguments]
@aws-device *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{root_dir}}/justfile" _project-aws-env device)"
    command aws "$@"

mod rig 'rig/justfile'
mod board 'devices/unit/board/justfile'
mod aws 'shared/aws/justfile'
mod mcu 'devices/unit/mcu/justfile'
mod web 'web/justfile'

@default:
    @just --list
