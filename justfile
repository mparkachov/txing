set shell := ["bash", "-eu", "-o", "pipefail", "-c"]
set quiet

root_dir := source_directory()

[private]
_project-aws-env scope='aws' region='' profile='' stack_name='' cognito_domain_prefix='' admin_email='' aws_shared_credentials_file='' env_file='':
    #!/usr/bin/env bash
    set -euo pipefail

    project_root="{{ root_dir }}"

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

    env_file="$(resolve_path "$(choose_value "{{ env_file }}" "config/aws.env")")"
    if [ -f "$env_file" ]; then
      # shellcheck disable=SC1090
      source "$env_file"
    fi
    unset AWS_CONFIG_FILE RIG_ENV_FILE BOARD_ENV_FILE

    normalize_slug() {
      printf '%s\n' "$1" \
        | tr '[:upper:]' '[:lower:]' \
        | tr -cs 'a-z0-9-' '-' \
        | sed 's/^-*//; s/-*$//'
    }

    require_value() {
      local label="$1"
      local value="$2"
      if [ -z "$value" ]; then
        echo "Missing required $label." >&2
        exit 1
      fi
      printf '%s\n' "$value"
    }

    normalize_required_slug() {
      local label="$1"
      local raw="$2"
      local normalized
      normalized="$(normalize_slug "$raw")"
      require_value "$label" "$normalized"
    }

    normalize_optional_slug() {
      local raw="$1"
      if [ -z "$raw" ]; then
        return 0
      fi
      normalize_slug "$raw"
    }

    scope="{{ scope }}"
    case "$scope" in
      aws|town|rig|device) ;;
      *)
        echo "Unsupported AWS environment scope '$scope'. Supported scopes: aws, town, rig, device." >&2
        exit 1
        ;;
    esac

    aws_region="$(require_value AWS_REGION "$(choose_value "{{ region }}" "${AWS_REGION:-}")")"
    aws_stack_name="$(choose_value "{{ stack_name }}" "${AWS_STACK_NAME:-txing-iot}")"
    aws_cognito_domain_prefix="$(choose_value "{{ cognito_domain_prefix }}" "${AWS_COGNITO_DOMAIN_PREFIX:-txing-iot}")"
    aws_admin_email="$(choose_value "{{ admin_email }}" "${AWS_ADMIN_EMAIL:-admin@example.com}")"
    aws_source_profile="${AWS_SOURCE_PROFILE:-${AWS_TOWN_PROFILE:-${AWS_PROFILE:-}}}"
    aws_town_profile="$aws_source_profile"
    aws_selected_profile="$(choose_value "{{ profile }}" "${AWS_SELECTED_PROFILE:-$aws_source_profile}")"
    aws_shared_credentials_file="$(resolve_path "$(choose_value "{{ aws_shared_credentials_file }}" "${AWS_SHARED_CREDENTIALS_FILE:-config/aws.credentials}")")"

    aws_lookup_flags=(--region "$aws_region")
    if [ -n "$aws_selected_profile" ]; then
      aws_lookup_flags+=(--profile "$aws_selected_profile")
    fi

    describe_thing_json() {
      local thing_id="$1"
      AWS_SHARED_CREDENTIALS_FILE="$aws_shared_credentials_file" \
      aws iot describe-thing \
        --thing-name "$thing_id" \
        "${aws_lookup_flags[@]}" \
        --output json
    }

    jq_string() {
      local json="$1"
      local query="$2"
      jq -r "$query // empty" <<<"$json"
    }

    txing_town_id="$(normalize_optional_slug "${TXING_TOWN_ID:-}")"
    txing_rig_id="$(normalize_optional_slug "${TXING_RIG_ID:-}")"
    txing_thing_id="$(normalize_optional_slug "${TXING_THING_ID:-}")"
    txing_town_name=""
    txing_rig_name=""
    txing_rig_type=""
    txing_device_name=""
    txing_device_type=""

    if [ "$scope" = "rig" ] || [ "$scope" = "device" ]; then
      if [ "$scope" = "device" ]; then
        txing_thing_id="$(normalize_required_slug TXING_THING_ID "$txing_thing_id")"
        device_json="$(describe_thing_json "$txing_thing_id")"
        txing_device_name="$(normalize_required_slug "device name" "$(jq_string "$device_json" '.attributes.name')")"
        txing_device_type="$(normalize_required_slug "device type" "$(jq_string "$device_json" '.thingTypeName')")"
        txing_rig_id="$(normalize_required_slug TXING_RIG_ID "$(jq_string "$device_json" '.attributes.rigId')")"
        txing_town_id="$(normalize_required_slug TXING_TOWN_ID "$(jq_string "$device_json" '.attributes.townId')")"
      else
        txing_rig_id="$(normalize_required_slug TXING_RIG_ID "$txing_rig_id")"
      fi

      rig_json="$(describe_thing_json "$txing_rig_id")"
      txing_rig_name="$(normalize_required_slug "rig name" "$(jq_string "$rig_json" '.attributes.name')")"
      txing_rig_type="$(normalize_required_slug "rig type" "$(jq_string "$rig_json" '.thingTypeName')")"
      txing_town_id="$(normalize_required_slug TXING_TOWN_ID "$(jq_string "$rig_json" '.attributes.townId')")"

      town_json="$(describe_thing_json "$txing_town_id")"
      txing_town_name="$(normalize_required_slug "town name" "$(jq_string "$town_json" '.attributes.name')")"
    elif [ "$scope" = "town" ] && [ -n "$txing_town_id" ]; then
      town_json="$(describe_thing_json "$txing_town_id")"
      txing_town_name="$(normalize_required_slug "town name" "$(jq_string "$town_json" '.attributes.name')")"
    fi

    txing_town_stack_name="${TXING_TOWN_STACK_NAME:-}"
    txing_rig_stack_name="${TXING_RIG_STACK_NAME:-}"
    txing_device_stack_name="${TXING_DEVICE_STACK_NAME:-}"

    rig_name="$txing_rig_id"
    rig_id="$txing_rig_id"
    sparkplug_group_id="$txing_town_id"
    sparkplug_edge_node_id="$txing_rig_id"
    cloudwatch_log_group="${CLOUDWATCH_LOG_GROUP:-}"
    if [ -n "${SCHEMA_FILE:-}" ]; then
      schema_file="$(resolve_path "$SCHEMA_FILE")"
    elif [ -n "$txing_device_type" ]; then
      if [ -f "$project_root/devices/${txing_device_type}/aws/board-shadow.schema.json" ]; then
        schema_file="$(resolve_path "devices/${txing_device_type}/aws/board-shadow.schema.json")"
      else
        schema_file=""
      fi
    else
      schema_file=""
    fi
    board_video_region="${BOARD_VIDEO_REGION:-$aws_region}"
    board_video_sender_command="${BOARD_VIDEO_SENDER_COMMAND:-}"
    kvs_dualstack_endpoints="${KVS_DUALSTACK_ENDPOINTS:-}"
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
    thing_name="$txing_thing_id"

    export_line TXING_PROJECT_ROOT "$project_root"
    export_line AWS_ENV_FILE "$env_file"
    printf 'unset RIG_ENV_FILE\n'
    printf 'unset BOARD_ENV_FILE\n'
    printf 'unset AWS_CONFIG_FILE\n'
    export_line AWS_REGION "$aws_region"
    export_line AWS_STACK_NAME "$aws_stack_name"
    export_line AWS_COGNITO_DOMAIN_PREFIX "$aws_cognito_domain_prefix"
    export_line AWS_ADMIN_EMAIL "$aws_admin_email"
    export_line AWS_SOURCE_PROFILE "$aws_source_profile"
    export_line AWS_TOWN_PROFILE "$aws_town_profile"
    export_line AWS_RIG_PROFILE "$aws_source_profile"
    export_line AWS_DEVICE_PROFILE "$aws_source_profile"
    export_line AWS_SELECTED_PROFILE "$aws_selected_profile"
    export_line AWS_SHARED_CREDENTIALS_FILE "$aws_shared_credentials_file"
    export_line TXING_TOWN_ID "$txing_town_id"
    export_line TXING_RIG_ID "$txing_rig_id"
    export_line TXING_THING_ID "$txing_thing_id"
    export_line TXING_RIG_TYPE "$txing_rig_type"
    export_line TXING_DEVICE_TYPE "$txing_device_type"
    export_line TXING_TOWN_STACK_NAME "$txing_town_stack_name"
    export_line TXING_RIG_STACK_NAME "$txing_rig_stack_name"
    export_line TXING_DEVICE_STACK_NAME "$txing_device_stack_name"
    export_line RIG_NAME "$rig_name"
    export_line RIG_ID "$rig_id"
    export_line RIG_TYPE "$txing_rig_type"
    export_line SPARKPLUG_GROUP_ID "$sparkplug_group_id"
    export_line SPARKPLUG_EDGE_NODE_ID "$sparkplug_edge_node_id"
    export_line CLOUDWATCH_LOG_GROUP "$cloudwatch_log_group"
    export_line THING_NAME "$thing_name"
    export_line SCHEMA_FILE "$schema_file"
    export_line BOARD_VIDEO_REGION "$board_video_region"
    export_line BOARD_VIDEO_SENDER_COMMAND "$board_video_sender_command"
    if [ -n "$kvs_dualstack_endpoints" ]; then
      export_line KVS_DUALSTACK_ENDPOINTS "$kvs_dualstack_endpoints"
    else
      printf 'unset KVS_DUALSTACK_ENDPOINTS\n'
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
    eval "$(just --justfile "{{ root_dir }}/justfile" _project-aws-env rig)"
    command aws "$@"

[positional-arguments]
@aws-town *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{ root_dir }}/justfile" _project-aws-env town)"
    command aws "$@"

[positional-arguments]
@aws-device *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{ root_dir }}/justfile" _project-aws-env device)"
    command aws "$@"

mod rig 'rig/justfile'
mod aws 'shared/aws/justfile'
mod witness 'witness/justfile'
mod unit 'devices/unit/justfile'
mod time 'devices/time/justfile'
mod web 'web/justfile'

@default:
    @just --list
