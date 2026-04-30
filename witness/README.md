# Witness

`witness/` is the standalone AWS IoT Sparkplug projection component.

It owns:

- the Sparkplug MQTT topic rule
- the witness Lambda
- the witness IAM role
- the witness log group

Deploy it independently with:

```bash
just witness::deploy
```

The default stack name is `${AWS_STACK_NAME}-witness`, derived from the shared repo AWS environment.

Public resource names use the witness stack name directly:

- Lambda function: `${witness-stack-name}`
- CloudWatch log group: `/aws/lambda/${witness-stack-name}`
- IoT Topic Rule: sanitized witness stack name with only letters, digits, and `_`
