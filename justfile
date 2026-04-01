set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

root_dir := source_directory()

[private]
_project-aws-env scope='rig' region='' profile='' endpoint_file='' stack_name='' cognito_domain_prefix='' admin_email='' aws_shared_credentials_file='' aws_config_file='' env_file='':
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

    txing_aws_town_profile_default="${TXING_AWS_TOWN_PROFILE:-town}"
    txing_aws_rig_profile_default="${TXING_AWS_RIG_PROFILE:-rig}"
    txing_aws_selected_profile_default="$txing_aws_rig_profile_default"
    if [ "{{scope}}" = "town" ]; then
      txing_aws_selected_profile_default="$txing_aws_town_profile_default"
    fi

    txing_aws_region="$(choose_value "{{region}}" "${TXING_AWS_REGION:-eu-central-1}")"
    txing_aws_stack_name="$(choose_value "{{stack_name}}" "${TXING_AWS_STACK_NAME:-txing-iot}")"
    txing_aws_cognito_domain_prefix="$(choose_value "{{cognito_domain_prefix}}" "${TXING_AWS_COGNITO_DOMAIN_PREFIX:-txing-iot}")"
    txing_aws_admin_email="$(choose_value "{{admin_email}}" "${TXING_AWS_ADMIN_EMAIL:-admin@example.com}")"
    txing_aws_town_profile="$txing_aws_town_profile_default"
    txing_aws_rig_profile="$txing_aws_rig_profile_default"
    txing_aws_selected_profile="$(choose_value "{{profile}}" "$txing_aws_selected_profile_default")"
    txing_aws_shared_credentials_file="$(resolve_path "$(choose_value "{{aws_shared_credentials_file}}" "${TXING_AWS_SHARED_CREDENTIALS_FILE:-config/aws.credentials}")")"
    txing_aws_config_file="$(resolve_path "$(choose_value "{{aws_config_file}}" "${TXING_AWS_CONFIG_FILE:-config/aws.config}")")"
    txing_aws_endpoint_file="$(resolve_path "$(choose_value "{{endpoint_file}}" "${TXING_AWS_ENDPOINT_FILE:-certs/iot-data-ats.endpoint}")")"

    export_line TXING_PROJECT_ROOT "$project_root"
    export_line TXING_AWS_ENV_FILE "$env_file"
    export_line TXING_AWS_REGION "$txing_aws_region"
    export_line TXING_AWS_STACK_NAME "$txing_aws_stack_name"
    export_line TXING_AWS_COGNITO_DOMAIN_PREFIX "$txing_aws_cognito_domain_prefix"
    export_line TXING_AWS_ADMIN_EMAIL "$txing_aws_admin_email"
    export_line TXING_AWS_TOWN_PROFILE "$txing_aws_town_profile"
    export_line TXING_AWS_RIG_PROFILE "$txing_aws_rig_profile"
    export_line TXING_AWS_SELECTED_PROFILE "$txing_aws_selected_profile"
    export_line TXING_AWS_SHARED_CREDENTIALS_FILE "$txing_aws_shared_credentials_file"
    export_line TXING_AWS_CONFIG_FILE "$txing_aws_config_file"
    export_line TXING_AWS_ENDPOINT_FILE "$txing_aws_endpoint_file"
    export_line AWS_SHARED_CREDENTIALS_FILE "$txing_aws_shared_credentials_file"
    export_line AWS_CONFIG_FILE "$txing_aws_config_file"
    export_line AWS_REGION "$txing_aws_region"
    export_line AWS_DEFAULT_REGION "$txing_aws_region"
    if [ -n "$txing_aws_selected_profile" ]; then
      export_line AWS_PROFILE "$txing_aws_selected_profile"
    else
      printf 'unset AWS_PROFILE\n'
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

mod rig 'rig/justfile'
mod board 'board/justfile'
mod aws 'aws/justfile'
mod mcu 'mcu/justfile'
mod web 'web/justfile'

@default:
    @just --list
