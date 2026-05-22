from __future__ import annotations

import boto3


cloudformation = None


def _cloudformation():
    global cloudformation
    if cloudformation is None:
        cloudformation = boto3.client("cloudformation")
    return cloudformation


def stack_status(stack_id: str) -> str:
    response = _cloudformation().describe_stacks(StackName=stack_id)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"CloudFormation stack not found: {stack_id}")
    status = stacks[0].get("StackStatus")
    if not isinstance(status, str) or not status:
        raise RuntimeError(f"CloudFormation stack has no status: {stack_id}")
    return status


def stack_is_deleting(stack_id: str) -> bool:
    return stack_status(stack_id).startswith("DELETE_")
