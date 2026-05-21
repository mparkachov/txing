#!/usr/bin/env bash

txing_aws_init() {
  if [ -z "${TXING_AWS_STACK:-}" ]; then
    echo "TXING_AWS_STACK is required for stack-backed txing AWS commands." >&2
    return 1
  fi
  TXING_AWS_REGION="$(aws configure get region 2>/dev/null || true)"
  if [ -z "$TXING_AWS_REGION" ]; then
    echo "AWS CLI region is not configured. Set it with 'aws configure set region <aws-region>' or in your AWS CLI config." >&2
    return 1
  fi
  export TXING_AWS_REGION
}

stack_output() {
  local stack_name="$1"
  local output_key="$2"
  local value
  value="$(
    aws cloudformation describe-stacks \
      --stack-name "$stack_name" \
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
    --query "Stacks[0].Outputs" \
    --output json | jq '.'
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
      --query Credentials \
      --output json
  )"
  export AWS_ACCESS_KEY_ID
  export AWS_SECRET_ACCESS_KEY
  export AWS_SESSION_TOKEN
  AWS_ACCESS_KEY_ID="$(jq -r '.AccessKeyId' <<<"$creds")"
  AWS_SECRET_ACCESS_KEY="$(jq -r '.SecretAccessKey' <<<"$creds")"
  AWS_SESSION_TOKEN="$(jq -r '.SessionToken' <<<"$creds")"
}

artifact_bucket_name() {
  local account_id
  account_id="$(aws sts get-caller-identity --query Account --output text)"
  printf 'txing-cfn-%s-%s-%s' "$account_id" "$TXING_AWS_REGION" "$TXING_AWS_STACK" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -cs 'a-z0-9.-' '-' \
    | sed 's/^-*//; s/-*$//' \
    | cut -c1-63 \
    | sed 's/[.]*$//'
}

deploy_init_parameter_name() {
  local parameter_key="$1"
  printf '/txing/stack/%s' "$parameter_key"
}

ensure_artifact_bucket() {
  local bucket_name
  bucket_name="$(
    artifact_bucket_name
  )"
  if [ -z "$bucket_name" ]; then
    echo "failed to derive CloudFormation artifact bucket name" >&2
    return 1
  fi
  if ! aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    if [ "$TXING_AWS_REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$bucket_name" >/dev/null
    else
      aws s3api create-bucket \
        --bucket "$bucket_name" \
        --create-bucket-configuration "LocationConstraint=$TXING_AWS_REGION" >/dev/null
    fi
  fi
  printf '%s\n' "$bucket_name"
}

empty_s3_bucket() {
  local bucket_name="$1"
  local page
  local delete_batch
  local delete_count
  if ! aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    echo "skip: bucket $bucket_name does not exist or is not accessible"
    return 0
  fi
  while true; do
    page="$(aws s3api list-object-versions --bucket "$bucket_name" --output json)"
    delete_batch="$(
      jq -c '{Objects: (((.Versions // []) + (.DeleteMarkers // [])) | map({Key, VersionId})), Quiet: true}' <<<"$page"
    )"
    delete_count="$(jq -r '.Objects | length' <<<"$delete_batch")"
    if [ "$delete_count" = "0" ]; then
      break
    fi
    aws s3api delete-objects \
      --bucket "$bucket_name" \
      --delete "$delete_batch" >/dev/null
  done
  while true; do
    page="$(aws s3api list-objects-v2 --bucket "$bucket_name" --output json)"
    delete_batch="$(
      jq -c '{Objects: ((.Contents // []) | map({Key})), Quiet: true}' <<<"$page"
    )"
    delete_count="$(jq -r '.Objects | length' <<<"$delete_batch")"
    if [ "$delete_count" = "0" ]; then
      break
    fi
    aws s3api delete-objects \
      --bucket "$bucket_name" \
      --delete "$delete_batch" >/dev/null
  done
  echo "emptied bucket $bucket_name"
}

delete_s3_bucket_if_exists() {
  local bucket_name="$1"
  if ! aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    echo "skip: bucket $bucket_name does not exist or is not accessible"
    return 0
  fi
  empty_s3_bucket "$bucket_name"
  aws s3api delete-bucket --bucket "$bucket_name"
  echo "deleted bucket $bucket_name"
}

deploy_template() {
  local stack_name="$1"
  local template_file="$2"
  shift 2
  local artifact_bucket
  local packaged_template_dir
  local packaged_template
  local parameter_overrides=()
  local parameter_values=()
  artifact_bucket="$(ensure_artifact_bucket)"
  packaged_template_dir="$(mktemp -d "${TMPDIR:-/tmp}/txing-cfn.XXXXXX")"
  packaged_template="$packaged_template_dir/template.yaml"
  aws cloudformation package \
    --template-file "$template_file" \
    --s3-bucket "$artifact_bucket" \
    --output-template-file "$packaged_template"
  if grep -q '^  LambdaArtifactsBucketName:' "$packaged_template"; then
    parameter_values+=("LambdaArtifactsBucketName=$artifact_bucket")
  fi
  if grep -q '^  AwsAdminCodeS3Key:' "$packaged_template"; then
    local admin_source_dir
    local admin_zip
    local admin_hash
    local admin_key
    admin_source_dir="python/src"
    admin_zip="$packaged_template_dir/aws-admin.zip"
    if [ ! -d "$admin_source_dir/aws_admin" ]; then
      echo "AWS admin Lambda source is missing: $admin_source_dir/aws_admin" >&2
      return 1
    fi
    (
      cd "$admin_source_dir"
      find aws aws_admin -type f \
        ! -path '*/__pycache__/*' \
        ! -name '*.pyc' \
        ! -name '*.pyo' \
        -print | LC_ALL=C sort | zip -q -X "$admin_zip" -@
    )
    if command -v shasum >/dev/null 2>&1; then
      admin_hash="$(shasum -a 256 "$admin_zip" | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
      admin_hash="$(sha256sum "$admin_zip" | awk '{print $1}')"
    else
      echo "shasum or sha256sum is required to package AWS admin Lambda code" >&2
      return 1
    fi
    admin_key="cfn/aws-admin/$admin_hash.zip"
    if ! aws s3api head-object --bucket "$artifact_bucket" --key "$admin_key" >/dev/null 2>&1; then
      aws s3 cp "$admin_zip" "s3://$artifact_bucket/$admin_key" >/dev/null
    fi
    parameter_values+=(
      "AwsAdminCodeS3Bucket=$artifact_bucket"
      "AwsAdminCodeS3Key=$admin_key"
    )
  fi
  if [ "${#parameter_values[@]}" -gt 0 ]; then
    parameter_overrides+=(--parameter-overrides "${parameter_values[@]}")
  fi
  if [ "${#parameter_overrides[@]}" -gt 0 ]; then
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$packaged_template" \
      --capabilities CAPABILITY_IAM \
      --no-fail-on-empty-changeset \
      "${parameter_overrides[@]}"
  else
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$packaged_template" \
      --capabilities CAPABILITY_IAM \
      --no-fail-on-empty-changeset
  fi
  rm -rf "$packaged_template_dir"
}

invoke_enlist_payload_file() {
  local payload_file="$1"
  local function_name
  local response_file
  local invoke_metadata_file
  function_name="$(stack_output "$TXING_AWS_STACK" EnlistFunctionName)"
  response_file="$(mktemp "${TMPDIR:-/tmp}/txing-enlist-response.XXXXXX")"
  invoke_metadata_file="$(mktemp "${TMPDIR:-/tmp}/txing-enlist-metadata.XXXXXX")"
  aws lambda invoke \
    --function-name "$function_name" \
    --cli-binary-format raw-in-base64-out \
    --payload "fileb://$payload_file" \
    "$response_file" >"$invoke_metadata_file"
  if jq -e '.FunctionError? // empty' "$invoke_metadata_file" >/dev/null; then
    cat "$response_file" >&2
    rm -f "$response_file" "$invoke_metadata_file"
    return 1
  fi
  if ! jq -e '.ok == true' "$response_file" >/dev/null; then
    cat "$response_file" >&2
    rm -f "$response_file" "$invoke_metadata_file"
    return 1
  fi
  cat "$response_file"
  rm -f "$response_file" "$invoke_metadata_file"
}

configure_indexing_and_wait() {
  local thing_indexing_configuration
  local deadline
  local thing_indexing_mode
  local thing_connectivity_indexing_mode
  local indexing_custom_fields
  thing_indexing_configuration='{"thingIndexingMode":"REGISTRY","thingConnectivityIndexingMode":"STATUS","customFields":[{"name":"attributes.name","type":"String"},{"name":"attributes.kind","type":"String"},{"name":"attributes.townId","type":"String"},{"name":"attributes.rigId","type":"String"}]}'
  aws iot update-indexing-configuration \
    --thing-indexing-configuration "$thing_indexing_configuration"
  deadline=$(( $(date +%s) + 90 ))
  while :; do
    thing_indexing_mode="$(
      aws iot get-indexing-configuration \
        --query "thingIndexingConfiguration.thingIndexingMode" \
        --output text 2>/dev/null || true
    )"
    thing_connectivity_indexing_mode="$(
      aws iot get-indexing-configuration \
        --query "thingIndexingConfiguration.thingConnectivityIndexingMode" \
        --output text 2>/dev/null || true
    )"
    indexing_custom_fields="$(
      aws iot get-indexing-configuration \
        --query "thingIndexingConfiguration.customFields[].name" \
        --output text 2>/dev/null || true
    )"
    if [ "$thing_indexing_mode" = "REGISTRY" ] \
      && [ "$thing_connectivity_indexing_mode" = "STATUS" ] \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.name" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.kind" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.townId" >/dev/null \
      && printf '%s\n' "$indexing_custom_fields" | tr '\t' '\n' | grep -Fx "attributes.rigId" >/dev/null; then
      break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "timed out waiting for AWS IoT fleet indexing configuration" >&2
      return 1
    fi
    sleep 3
  done
  aws iot get-indexing-configuration \
    --query "thingIndexingConfiguration" \
    --output json
}
