# time device

`time` is the previous AWS-hosted software device type. It is no longer part of
the active cloud architecture and is not deployed by the root AWS stack.

New AWS-hosted cloud devices use `devices/cloud-mcu`, the
`/txing/town/cloud/cloud-mcu` type catalog path, `txing-cloud-rig-lambda`, and
`txing-cloud-mcu-lambda`.

Existing deployed `time` things, named shadows, and Lambda resources are manual
cleanup only after the forward-only cloud MCU deployment is verified.
