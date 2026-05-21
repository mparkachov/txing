from __future__ import annotations

import unittest
from unittest.mock import patch
from typing import Any

from aws_admin import clean_stack


class CleanStackTests(unittest.TestCase):
    def test_fleet_indexing_configuration_is_structured(self) -> None:
        config = clean_stack._fleet_indexing_configuration()

        self.assertEqual(config["thingIndexingMode"], "REGISTRY")
        self.assertEqual(config["thingConnectivityIndexingMode"], "STATUS")
        self.assertEqual(
            config["customFields"],
            [
                {"name": "attributes.name", "type": "String"},
                {"name": "attributes.kind", "type": "String"},
                {"name": "attributes.townId", "type": "String"},
                {"name": "attributes.rigId", "type": "String"},
            ],
        )

    def test_delete_policy_attachments_detaches_targets(self) -> None:
        class FakeIot:
            def __init__(self) -> None:
                self.detached: list[tuple[str, str]] = []

            def list_targets_for_policy(self, **kwargs: Any) -> dict[str, Any]:
                if kwargs["policyName"] != "policy":
                    raise AssertionError(kwargs)
                return {"targets": ["cert/b", "cert/a", "cert/a"]}

            def detach_policy(self, *, policyName: str, target: str) -> None:
                self.detached.append((policyName, target))

        fake = FakeIot()
        original = clean_stack.iot
        clean_stack.iot = fake
        try:
            result = clean_stack._handle_delete(
                {"CleanupType": "IotPolicyAttachments", "PolicyNames": ["policy"]}
            )
        finally:
            clean_stack.iot = original

        self.assertEqual(
            result,
            {"policies": {"policy": {"detachedTargets": 2, "missing": False}}},
        )
        self.assertEqual(fake.detached, [("policy", "cert/a"), ("policy", "cert/b")])

    def test_type_catalog_create_rejects_non_map_parameters(self) -> None:
        with self.assertRaisesRegex(TypeError, "CatalogParameters must be a map"):
            clean_stack._put_type_catalog_parameters(
                {
                    "ThingTypeName": "unit",
                    "CatalogBasePath": "/txing/town/raspi/unit",
                    "CatalogParameters": [],
                }
            )

    def test_lambda_delete_skips_cleanup_during_stack_update(self) -> None:
        event = {
            "RequestType": "Delete",
            "ResponseURL": "https://cloudformation-response.example",
            "StackId": "stack",
            "RequestId": "request",
            "LogicalResourceId": "TxingIotPolicyAttachmentCleanup",
            "ResourceProperties": {
                "CleanupType": "IotPolicyAttachments",
                "PolicyNames": ["policy"],
            },
        }
        sent: list[dict[str, Any]] = []

        def send_response(
            event: dict[str, Any],
            context: object,
            status: str,
            data: dict[str, Any] | None = None,
            reason: str | None = None,
            physical_resource_id: str | None = None,
        ) -> None:
            sent.append({"status": status, "data": dict(data or {})})

        with (
            patch.object(clean_stack, "stack_is_deleting", return_value=False),
            patch.object(clean_stack, "_send_response", side_effect=send_response),
            patch.object(clean_stack, "_handle_delete") as handle_delete,
        ):
            clean_stack.lambda_handler(event, object())

        handle_delete.assert_not_called()
        self.assertEqual(
            sent,
            [
                {
                    "status": "SUCCESS",
                    "data": {"skipped": True, "reason": "stack is not deleting"},
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
