# Retire the temporary virtual quad deployment

This procedure applies to account `453102798330` in `eu-central-1`. Retire
the temporary resources after the [permanent device passes acceptance](README.md#permanent-deployment-acceptance).
Use the AWS profile for that account. Retain the relevant acceptance and
failure evidence in the GitHub issue or approved private storage before
deleting logs or artifacts.

| Scope | Resources |
| --- | --- |
| Temporary registered device | `virtual-quad-eypfeo` on `cloud-ikgp4n` (Office name `virtual-quad-test`), its five named shadows, channels `virtual-quad-eypfeo-board-video` and `virtual-quad-eypfeo-mavlink`, and its item in `town-virtual-quad-sessions`. |
| Temporary rig | `cloud-ikgp4n`, `sparkplug` named shadow, and its membership in `txing-rig-type-cloud`. |
| Standalone feasibility run | MicroVM image and CloudFormation stack `quad-qualification-microvm-176`, bucket `quad-qualification-microvm-176-artifacts-adzkvmdxvocd`, CloudWatch group `/aws/lambda-microvms/quad-qualification-microvm-176`, and stack-owned roles `quad-qualification-microvm-176-BuildRole-1Jl4Vfs7Mft9` and `quad-qualification-microvm-176-ExecutionRole-fEJtHmXiOjic`. Channels `quad-qualification-176-board-video` and `quad-qualification-176-mavlink`. |
| Permanent device and shared services | `virtual-quad-1knemq` on `cloud-8lgj1r` (Office name `aws`), both permanent channels, shared cloud rig and observer schedules, `town-virtual-quad` controller and repair schedule, session table, artifact bucket and retained production image versions. Keep these available. |

The removed Fargate prototype used stack and repository
`quad-qualification-176`. Both were absent on the last inventory. The KVS
names were reused for the standalone MicroVM. [Feasibility history](https://github.com/mparkachov/txing/issues/176)

## Temporary device and rig

Use this shell setup for the manual commands below.

```sh
aws_quad() { aws --region eu-central-1 --no-cli-pager "$@"; }
aws_quad sts get-caller-identity --query Account --output text
device=virtual-quad-eypfeo
rig=cloud-ikgp4n
table=town-virtual-quad-sessions
key=$(jq -cn --arg id "$device" '{deviceId:{S:$id}}')
mkdir -p tmp
```

1. Confirm the account and verify the target's registry assignment using
   `aws_quad iot describe-thing --thing-name "$device"`. In Office, select
   REDCON 4 for the temporary device and follow the
   [drain procedure](README.md#drain-and-rollback). Confirm its agent and
   simulator are terminal. Keep the rig's shared census schedule enabled.
   A cloud rig REDCON 4 command disables that schedule for the environment.
2. Read the session item with a consistent read. Check for no current
   session and retain the version for conditional deletion. A missing item
   already needs no deletion.

   ```sh
   version=$(aws_quad dynamodb get-item --table-name "$table" \\
     --key "$key" --consistent-read --output json | jq -er '
       if .Item == null then "absent"
       elif (.Item.record.B | @base64d | fromjson | .session) == null
       then .Item.version.N else error("session still active") end')
   ```

3. Confirm the temporary Thing has no attached principals or groups with
   `iot list-thing-principals` and `iot list-thing-groups-for-thing`. Delete
   the device registry entry first to stop discovery and new reservations.
   To fence a concurrent registry update, use the version from
   `aws_quad iot describe-thing --thing-name "$device" --query version --output text`.

   ```sh
   aws_quad iot delete-thing --thing-name "$device" --expected-version <thing-version>
   ```

4. If the drained ledger item existed, remove it only at the inspected
   version. Recheck state if the condition fails. A command that raced
   registry deletion may require the repair schedule to finish its drain.

   ```sh
   if [ "$version" != absent ]; then
     aws_quad dynamodb delete-item --table-name "$table" --key "$key" \\
       --condition-expression '#v = :v' --expression-attribute-names '{"#v":"version"}' \\
       --expression-attribute-values "$(jq -cn --arg v "$version" '{":v":{N:$v}}')"
   fi
   ```

5. List the remaining named shadows with
   `aws_quad iot-data list-named-shadows-for-thing --thing-name "$device"`.
   Remove the registered `sparkplug`, `simulation`, `video`, `mavlink`
   and `agent` shadows. For each name returned, use the same operation as
   in this example.

   ```sh
   aws_quad iot-data delete-thing-shadow --thing-name "$device" \\
     --shadow-name simulation tmp/virtual-quad-deleted-shadow.json
   ```

6. Resolve each temporary channel's ARN by exact name. Remove each resolved
   ARN and verify that `describe-signaling-channel` returns
   `ResourceNotFoundException` as deletion completes.

   ```sh
   channel="$device-board-video"
   channel_arn=$(aws_quad kinesisvideo describe-signaling-channel --channel-name "$channel" \\
     --query ChannelInfo.ChannelARN --output text) &&
     aws_quad kinesisvideo delete-signaling-channel --channel-arn "$channel_arn"
   ```

   Repeat with `channel="$device-mavlink"`. A `ResourceNotFoundException`
   confirms that the named channel is absent.

7. Confirm no Things remain assigned to the temporary rig.

   ```sh
   aws_quad iot list-things --attribute-name rigId --attribute-value "$rig" --query 'things[].thingName'
   ```

   After confirming the rig has no principals, remove only its membership
   in the shared group, then delete the rig Thing and its `sparkplug` shadow.

   ```sh
   aws_quad iot remove-thing-from-thing-group --thing-name "$rig" --thing-group-name txing-rig-type-cloud
   aws_quad iot delete-thing --thing-name "$rig" --expected-version <rig-thing-version>
   aws_quad iot-data delete-thing-shadow --thing-name "$rig" \\
     --shadow-name sparkplug tmp/virtual-quad-deleted-rig-shadow.json
   ```

8. Verify both Things are absent, their named-shadow lists are empty, both
   channels are absent, and a consistent read returns no test ledger item.
   Verify the permanent device remains discoverable, both of its KVS
   channels are present and the shared census and simulator repair
   schedules are enabled. Leave shared log groups to their retention
   policies.

## Standalone MicroVM feasibility resources

Use the same account and region. Resolve the stack resources and validate
their ownership before deleting any S3 objects or IAM resources.

```sh
probe=quad-qualification-microvm-176
probe_image="arn:aws:lambda:eu-central-1:453102798330:microvm-image:$probe"
aws_quad cloudformation describe-stack-resources --stack-name "$probe" \\
  --query 'StackResources[].[ResourceType,PhysicalResourceId]'
aws_quad lambda-microvms list-microvms --image-identifier "$probe_image" \\
  --query 'items[].[microvmId,state]'
```

1. Confirm all instances for the dedicated image are terminal. Delete the
   image by its ARN and verify it is deleted before removing artifacts.

   ```sh
   aws_quad lambda-microvms delete-microvm-image --image-identifier "$probe_image"
   ```

   Use `aws_quad lambda-microvms get-microvm-image --image-identifier "$probe_image"`
   to confirm deletion.
2. Check bucket versioning and contents. The dedicated bucket was
   unversioned with two bundle objects. Preserve required evidence, then
   empty only that verified bucket. If versioning has since changed, inspect
   object versions and delete markers and remove the dedicated versions
   before deleting the stack. Check for unfinished uploads with
   `s3api list-multipart-uploads` and abort any belonging to this bucket.

   ```sh
   bucket=quad-qualification-microvm-176-artifacts-adzkvmdxvocd
   aws_quad s3api get-bucket-versioning --bucket "$bucket"
   aws_quad s3 ls "s3://$bucket/" --recursive
   aws_quad s3 rm "s3://$bucket/" --recursive
   ```

3. Delete the dedicated stack and wait for it. It owns the bucket, roles
   and log group listed above.

   ```sh
   aws_quad cloudformation delete-stack --stack-name "$probe"
   aws_quad cloudformation wait stack-delete-complete --stack-name "$probe"
   ```

4. Resolve and delete the exact standalone channels
   `quad-qualification-176-board-video` and
   `quad-qualification-176-mavlink` using the channel procedure above.
5. Verify the image, stack, bucket, stack-owned roles and log group, and
   both channels are absent. Record the result in
   [#183](https://github.com/mparkachov/txing/issues/183).

[AWS Thing deletion](https://docs.aws.amazon.com/iot/latest/developerguide/delete-thing.html)
· [Shadow deletion](https://docs.aws.amazon.com/iot/latest/apireference/API_iotdata_DeleteThingShadow.html)
· [MicroVM image lifecycle](https://docs.aws.amazon.com/lambda/latest/dg/microvms-images.html)
