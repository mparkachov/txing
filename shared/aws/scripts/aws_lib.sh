#!/bin/sh

txing_ensure_tmpdir() {
  if [ -n "${TXING_PROJECT_ROOT:-}" ]; then
    TMPDIR="$TXING_PROJECT_ROOT/tmp"
    export TMPDIR
  fi
  if [ -n "${TMPDIR:-}" ]; then
    mkdir -p "$TMPDIR"
  fi
}

txing_aws_init() {
  txing_ensure_tmpdir
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

stack_parameter_name() {
  parameter_key="$1"
  case "$parameter_key" in
    /*) printf '%s\n' "$parameter_key" ;;
    *) printf '/txing/stack/%s\n' "$parameter_key" ;;
  esac
}

stack_parameter() {
  parameter_name="$(stack_parameter_name "$1")"
  value="$(
    aws ssm get-parameter \
      --name "$parameter_name" \
      --with-decryption \
      --query Parameter.Value \
      --output text
  )"
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "SSM parameter $parameter_name is missing or empty" >&2
    return 1
  fi
  printf '%s\n' "$value"
}

describe_stack_parameters() {
  aws ssm get-parameters-by-path \
    --path /txing/stack \
    --recursive \
    --with-decryption \
    --query 'Parameters[].{Name:Name,Value:Value}' \
    --output json | jq 'sort_by(.Name)'
}

_resolve_unique_thing_name() {
  label="$1"
  query="$2"
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

artifact_bucket_name() {
  account_id="$(aws sts get-caller-identity --query Account --output text)"
  printf 'txing-cfn-%s-%s-%s' "$account_id" "$TXING_AWS_REGION" "$TXING_AWS_STACK" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -cs 'a-z0-9.-' '-' \
    | sed 's/^-*//; s/-*$//' \
    | cut -c1-63 \
    | sed 's/[.]*$//'
}

base_stack_name() {
  printf '%s\n' "${TXING_AWS_BASE_STACK:-$TXING_AWS_STACK-aws-base}"
}

deploy_init_parameter_name() {
  parameter_key="$1"
  stack_parameter_name "$parameter_key"
}

lambda_stack_name() {
  stack_suffix="$1"
  printf '%s-%s' "$TXING_AWS_STACK" "$stack_suffix"
}

lambda_release_targets_json() {
  jq -cn \
    --arg witness "$(stack_parameter WitnessFunctionName)" \
    --arg cloud_rig "$(stack_parameter CloudRigRuntimeFunctionName)" \
    --arg cloud_mcu "$(stack_parameter CloudMcuRuntimeFunctionName)" \
    '{
      "txing-witness-lambda": $witness,
      "txing-cloud-rig-lambda": $cloud_rig,
      "txing-cloud-mcu-lambda": $cloud_mcu
    }'
}

template_log_group_names() {
  template_file="$1"
  environment_stack_name="$2"
  cloudformation_stack_name="$3"
  awk '
    /^[ ]+LogGroupName:[ ]+!Sub[ ]+/ {
      line = $0
      sub(/^[ ]+LogGroupName:[ ]+!Sub[ ]+/, "", line)
      print line
    }
  ' "$template_file" | while IFS= read -r log_group_name; do
    printf '%s\n' "$log_group_name" \
      | sed \
          -e "s|\${EnvironmentStackName}|$environment_stack_name|g" \
          -e "s|\${AWS::StackName}|$cloudformation_stack_name|g"
  done
}

preflight_named_log_groups() {
  stack_name="$1"
  template_file="$2"
  shift 2
  environment_stack_name="$TXING_AWS_STACK"
  for parameter_override in "$@"; do
    case "$parameter_override" in
      EnvironmentStackName=*)
        environment_stack_name="${parameter_override#EnvironmentStackName=}"
        ;;
    esac
  done

  log_group_names="$(template_log_group_names "$template_file" "$environment_stack_name" "$stack_name")"
  if [ -z "$log_group_names" ]; then
    return 0
  fi

  stack_log_groups="$(
    aws cloudformation describe-stack-resources \
      --stack-name "$stack_name" \
      --query "StackResources[?ResourceType=='AWS::Logs::LogGroup'].PhysicalResourceId" \
      --output text 2>/dev/null || true
  )"
  conflict_count=0
  for log_group_name in $log_group_names; do
    if printf '%s\n' "$stack_log_groups" | tr '\t' '\n' | grep -Fx "$log_group_name" >/dev/null; then
      continue
    fi
    existing_log_group="$(
      aws logs describe-log-groups \
        --log-group-name-prefix "$log_group_name" \
        --output json 2>/dev/null \
        | jq -r --arg name "$log_group_name" '.logGroups[]?.logGroupName | select(. == $name)' \
        | sed -n '1p'
    )"
    if [ -n "$existing_log_group" ]; then
      if [ "$conflict_count" -eq 0 ]; then
        echo "CloudFormation cannot create stack $stack_name because named log groups already exist outside that stack:" >&2
      fi
      printf '  - %s\n' "$existing_log_group" >&2
      conflict_count=$((conflict_count + 1))
    fi
  done

  if [ "$conflict_count" -ne 0 ]; then
    echo "These log groups may contain useful failure logs. Preserve or export them, then import them into CloudFormation, delete them manually, or use a different TXING_AWS_STACK prefix before rerunning deploy." >&2
    return 1
  fi
}

delete_cloudformation_stack_if_exists() {
  stack_name="$1"
  wait_for_delete="$2"
  if ! aws cloudformation describe-stacks --stack-name "$stack_name" >/dev/null 2>&1; then
    echo "skip: CloudFormation stack $stack_name does not exist"
    return 0
  fi
  echo "Deleting CloudFormation stack $stack_name"
  aws cloudformation delete-stack --stack-name "$stack_name"
  if [ "$wait_for_delete" = "true" ]; then
    aws cloudformation wait stack-delete-complete --stack-name "$stack_name"
    echo "Deleted CloudFormation stack $stack_name"
  fi
}

ensure_artifact_bucket() {
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

ensure_lambda_seed_artifact() {
  artifact_id="$1"
  bucket_name="$2"
  object_key="lambda/$artifact_id/current/bootstrap.zip"
  if aws s3api head-object --bucket "$bucket_name" --key "$object_key" >/dev/null 2>&1; then
    return 0
  fi
  seed_dir="$(mktemp -d "${TMPDIR:-/tmp}/txing-lambda-seed.XXXXXX")"
  seed_zip="$seed_dir/bootstrap.zip"
  (
    cd "$seed_dir"
    {
      printf '#!/bin/sh\n'
      printf 'echo "txing lambda seed artifact; publish a release before invoking this function" >&2\n'
      printf 'exit 1\n'
    } >bootstrap
    chmod 755 bootstrap
    zip -q -X "$seed_zip" bootstrap
  )
  aws s3 cp "$seed_zip" "s3://$bucket_name/$object_key" >/dev/null
  rm -rf "$seed_dir"
  printf 'seeded lambda artifact s3://%s/%s\n' "$bucket_name" "$object_key"
}

empty_s3_bucket() {
  bucket_name="$1"
  if ! aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    echo "skip: bucket $bucket_name does not exist or is not accessible"
    return 0
  fi
  while true; do
    page="$(aws s3api list-object-versions --bucket "$bucket_name" --output json)"
    delete_batch="$(
      printf '%s\n' "$page" | jq -c '{Objects: (((.Versions // []) + (.DeleteMarkers // [])) | map({Key, VersionId})), Quiet: true}'
    )"
    delete_count="$(printf '%s\n' "$delete_batch" | jq -r '.Objects | length')"
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
      printf '%s\n' "$page" | jq -c '{Objects: ((.Contents // []) | map({Key})), Quiet: true}'
    )"
    delete_count="$(printf '%s\n' "$delete_batch" | jq -r '.Objects | length')"
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
  bucket_name="$1"
  if ! aws s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1; then
    echo "skip: bucket $bucket_name does not exist or is not accessible"
    return 0
  fi
  empty_s3_bucket "$bucket_name"
  aws s3api delete-bucket --bucket "$bucket_name"
  echo "deleted bucket $bucket_name"
}

upload_packaged_template() {
  bucket_name="$1"
  template_file="$2"
  if command -v shasum >/dev/null 2>&1; then
    template_hash="$(shasum -a 256 "$template_file" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    template_hash="$(sha256sum "$template_file" | awk '{print $1}')"
  else
    echo "shasum or sha256sum is required to upload CloudFormation templates" >&2
    return 1
  fi
  template_key="cfn/templates/$template_hash.yaml"
  if ! aws s3api head-object --bucket "$bucket_name" --key "$template_key" >/dev/null 2>&1; then
    aws s3 cp "$template_file" "s3://$bucket_name/$template_key" >/dev/null
  fi
  printf 'https://%s.s3.%s.amazonaws.com/%s\n' "$bucket_name" "$TXING_AWS_REGION" "$template_key"
}

deploy_template() {
  txing_ensure_tmpdir
  stack_name="$1"
  template_file="$2"
  shift 2
  preflight_named_log_groups "$stack_name" "$template_file" "$@"
  parameter_count=$#
  lambda_artifacts_bucket_parameter=""
  aws_admin_code_bucket_parameter=""
  aws_admin_code_key_parameter=""
  artifact_bucket="$(ensure_artifact_bucket)"
  packaged_template_dir="$(mktemp -d "${TMPDIR:-/tmp}/txing-cfn.XXXXXX")"
  packaged_template="$packaged_template_dir/template.yaml"
  aws cloudformation package \
    --template-file "$template_file" \
    --s3-bucket "$artifact_bucket" \
    --output-template-file "$packaged_template"
  if grep -q '^  LambdaArtifactsBucketName:' "$packaged_template"; then
    lambda_artifacts_bucket_parameter="LambdaArtifactsBucketName=$artifact_bucket"
  fi
  if grep -q '^  AwsAdminCodeS3Key:' "$packaged_template"; then
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
    aws_admin_code_bucket_parameter="AwsAdminCodeS3Bucket=$artifact_bucket"
    aws_admin_code_key_parameter="AwsAdminCodeS3Key=$admin_key"
  fi
  if [ "$parameter_count" -gt 0 ] || [ -n "$lambda_artifacts_bucket_parameter$aws_admin_code_bucket_parameter$aws_admin_code_key_parameter" ]; then
    set -- --parameter-overrides "$@"
    if [ -n "$lambda_artifacts_bucket_parameter" ]; then
      set -- "$@" "$lambda_artifacts_bucket_parameter"
    fi
    if [ -n "$aws_admin_code_bucket_parameter" ]; then
      set -- "$@" "$aws_admin_code_bucket_parameter"
    fi
    if [ -n "$aws_admin_code_key_parameter" ]; then
      set -- "$@" "$aws_admin_code_key_parameter"
    fi
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$packaged_template" \
      --s3-bucket "$artifact_bucket" \
      --capabilities CAPABILITY_NAMED_IAM \
      --no-fail-on-empty-changeset \
      "$@"
  else
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$packaged_template" \
      --s3-bucket "$artifact_bucket" \
      --capabilities CAPABILITY_NAMED_IAM \
      --no-fail-on-empty-changeset
  fi
  rm -rf "$packaged_template_dir"
}

invoke_enlist_payload_file() {
  txing_ensure_tmpdir
  payload_file="$1"
  function_name="$(stack_parameter EnlistFunctionName)"
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
