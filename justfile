set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

root_dir := source_directory()

[private]
_project-aws-env scope='rig' region='' profile='' stack_name='' cognito_domain_prefix='' admin_email='' aws_shared_credentials_file='' aws_config_file='' env_file='':
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

    aws_town_profile_default="${AWS_TOWN_PROFILE:-town}"
    aws_rig_profile_default="${AWS_RIG_PROFILE:-rig}"
    aws_txing_profile_default="${AWS_TXING_PROFILE:-txing}"
    aws_selected_profile_default="$aws_rig_profile_default"
    if [ "{{scope}}" = "town" ]; then
      aws_selected_profile_default="$aws_town_profile_default"
    elif [ "{{scope}}" = "txing" ]; then
      aws_selected_profile_default="$aws_txing_profile_default"
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
    thing_name="${THING_NAME:-txing}"
    schema_file="$(resolve_path "${SCHEMA_FILE:-docs/txing-shadow.schema.json}")"
    board_video_viewer_url="${BOARD_VIDEO_VIEWER_URL:-}"
    board_video_region="${BOARD_VIDEO_REGION:-eu-central-1}"
    board_video_channel_name="${BOARD_VIDEO_CHANNEL_NAME:-txing-board-video}"
    board_video_sender_command="${BOARD_VIDEO_SENDER_COMMAND:-}"
    kvs_dualstack_endpoints="${KVS_DUALSTACK_ENDPOINTS:-}"

    export_line TXING_PROJECT_ROOT "$project_root"
    export_line AWS_ENV_FILE "$env_file"
    export_line AWS_REGION "$aws_region"
    export_line AWS_STACK_NAME "$aws_stack_name"
    export_line AWS_COGNITO_DOMAIN_PREFIX "$aws_cognito_domain_prefix"
    export_line AWS_ADMIN_EMAIL "$aws_admin_email"
    export_line AWS_TOWN_PROFILE "$aws_town_profile"
    export_line AWS_RIG_PROFILE "$aws_rig_profile"
    export_line AWS_TXING_PROFILE "$aws_txing_profile_default"
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
@aws-txing *args:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just --justfile "{{root_dir}}/justfile" _project-aws-env txing)"
    command aws "$@"

mod rig 'rig/justfile'
mod board 'board/justfile'
mod aws 'shared/aws/justfile'
mod mcu 'mcu/justfile'
mod web 'web/justfile'

@default:
    @just --list
