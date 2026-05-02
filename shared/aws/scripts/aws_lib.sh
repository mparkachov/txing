#!/usr/bin/env bash

txing_aws_init() {
  if [ -z "${AWS_REGION:-}" ]; then
    echo "AWS_REGION is empty. Set it in config/aws.env or pass region=<aws-region>." >&2
    return 1
  fi
  aws_flags=(--region "$AWS_REGION")
  if [ -n "${AWS_SELECTED_PROFILE:-}" ]; then
    aws_flags+=(--profile "$AWS_SELECTED_PROFILE")
  fi
}

stack_output() {
  local stack_name="$1"
  local output_key="$2"
  local value
  value="$(
    aws cloudformation describe-stacks \
      --stack-name "$stack_name" \
      "${aws_flags[@]}" \
      --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue | [0]" \
      --output text
  )"
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "CloudFormation output $output_key not found in stack $stack_name" >&2
    return 1
  fi
  printf '%s\n' "$value"
}

describe_stack_outputs() {
  local stack_name="$1"
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    "${aws_flags[@]}" \
    --query "Stacks[0].Outputs" \
    --output table
}

_resolve_unique_thing_name() {
  local label="$1"
  local query="$2"
  local count
  count="$(
    aws iot search-index \
      --index-name AWS_Things \
      --query-string "$query" \
      --max-results 2 \
      "${aws_flags[@]}" \
      --query 'length(things)' \
      --output text
  )"
  if [ "$count" = "0" ]; then
    echo "$label was not found in AWS IoT registry" >&2
    return 1
  fi
  if [ "$count" != "1" ]; then
    echo "$label matched multiple AWS IoT things" >&2
    return 1
  fi
  aws iot search-index \
    --index-name AWS_Things \
    --query-string "$query" \
    --max-results 1 \
    "${aws_flags[@]}" \
    --query 'things[0].thingName' \
    --output text
}

resolve_town_thing_name() {
  if [ -n "${TXING_TOWN_ID:-}" ]; then
    printf '%s\n' "$TXING_TOWN_ID"
    return 0
  fi
  echo "TXING_TOWN_ID is required" >&2
  return 1
}

resolve_rig_thing_name() {
  if [ -n "${TXING_RIG_ID:-}" ]; then
    printf '%s\n' "$TXING_RIG_ID"
    return 0
  fi
  echo "TXING_RIG_ID is required" >&2
  return 1
}

resolve_device_thing_name() {
  if [ -n "${TXING_THING_ID:-}" ]; then
    printf '%s\n' "$TXING_THING_ID"
    return 0
  fi
  echo "TXING_THING_ID is required" >&2
  return 1
}

assume_stack_role() {
  local stack_name="$1"
  local output_key="$2"
  local role_arn
  local creds
  role_arn="$(stack_output "$stack_name" "$output_key")"
  creds="$(
    aws sts assume-role \
      --role-arn "$role_arn" \
      --role-session-name "txing-${output_key}-$(date -u +%Y%m%dT%H%M%SZ)" \
      "${aws_flags[@]}" \
      --query Credentials \
      --output json
  )"
  export AWS_ACCESS_KEY_ID
  export AWS_SECRET_ACCESS_KEY
  export AWS_SESSION_TOKEN
  AWS_ACCESS_KEY_ID="$(jq -r '.AccessKeyId' <<<"$creds")"
  AWS_SECRET_ACCESS_KEY="$(jq -r '.SecretAccessKey' <<<"$creds")"
  AWS_SESSION_TOKEN="$(jq -r '.SessionToken' <<<"$creds")"
  unset AWS_PROFILE AWS_DEFAULT_PROFILE
  aws_flags=(--region "$AWS_REGION")
}

ensure_artifact_bucket() {
  local account_id
  local bucket_name
  account_id="$(aws sts get-caller-identity "${aws_flags[@]}" --query Account --output text)"
  bucket_name="$(
    printf 'txing-cfn-%s-%s-%s' "$account_id" "$AWS_REGION" "$AWS_STACK_NAME" \
      | tr '[:upper:]' '[:lower:]' \
      | tr -cs 'a-z0-9.-' '-' \
      | sed 's/^-*//; s/-*$//'
  )"
  bucket_name="${bucket_name:0:63}"
  bucket_name="${bucket_name%.}"
  if [ -z "$bucket_name" ]; then
    echo "failed to derive CloudFormation artifact bucket name" >&2
    return 1
  fi
  if ! aws s3api head-bucket --bucket "$bucket_name" "${aws_flags[@]}" >/dev/null 2>&1; then
    if [ "$AWS_REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$bucket_name" "${aws_flags[@]}" >/dev/null
    else
      aws s3api create-bucket \
        --bucket "$bucket_name" \
        --create-bucket-configuration "LocationConstraint=$AWS_REGION" \
        "${aws_flags[@]}" >/dev/null
    fi
  fi
  printf '%s\n' "$bucket_name"
}

deploy_template() {
  local stack_name="$1"
  local template_file="$2"
  shift 2
  local artifact_bucket
  local packaged_template
  artifact_bucket="$(ensure_artifact_bucket)"
  packaged_template="$(mktemp "${TMPDIR:-/tmp}/txing-cfn.XXXXXX.yaml")"
  aws cloudformation package \
    --template-file "$template_file" \
    --s3-bucket "$artifact_bucket" \
    --output-template-file "$packaged_template" \
    "${aws_flags[@]}"
  aws cloudformation deploy \
    --stack-name "$stack_name" \
    --template-file "$packaged_template" \
    --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    "$@" \
    "${aws_flags[@]}"
  rm -f "$packaged_template"
}

configure_indexing_and_wait() {
  local thing_indexing_configuration
  local deadline
  local thing_indexing_mode
  local thing_connectivity_indexing_mode
  local indexing_custom_fields
  thing_indexing_configuration='{"thingIndexingMode":"REGISTRY","thingConnectivityIndexingMode":"STATUS","customFields":[{"name":"attributes.name","type":"String"},{"name":"attributes.townId","type":"String"},{"name":"attributes.rigId","type":"String"},{"name":"attributes.rigType","type":"String"},{"name":"attributes.deviceType","type":"String"}]}'
  aws iot update-indexing-configuration \
    "${aws_flags[@]}" \
    --thing-indexing-configuration "$thing_indexing_configuration"
  deadline=$(( $(date +%s) + 90 ))
  while :; do
    thing_indexing_mode="$(
      aws iot get-indexing-configuration \
        "${aws_flags[@]}" \
        --query "thingIndexingConfiguration.thingIndexingMode" \
        --output text 2>/dev/null || true
    )"
    thing_connectivity_indexing_mode="$(
      aws iot get-indexing-configuration \
        "${aws_flags[@]}" \
        --query "thingIndexingConfiguration.thingConnectivityIndexingMode" \
        --output text 2>/dev/null || true
    )"
    indexing_custom_fields="$(
      aws iot get-indexing-configuration \
        "${aws_flags[@]}" \
        --query "thingIndexingConfiguration.customFields[].name" \
        --output text 2>/dev/null || true
    )"
    if [ "$thing_indexing_mode" = "REGISTRY" ] \
      && [ "$thing_connectivity_indexing_mode" = "STATUS" ] \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.name" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.townId" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.rigId" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.rigType" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.deviceType" >/dev/null; then
      break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "timed out waiting for AWS IoT fleet indexing configuration" >&2
      return 1
    fi
    sleep 3
  done
  aws iot get-indexing-configuration \
    "${aws_flags[@]}" \
    --query "thingIndexingConfiguration" \
    --output json
}
