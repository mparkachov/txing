from __future__ import annotations

import asyncio
import unittest

from awsiot.greengrasscoreipc.model import (
    BinaryMessage,
    MessageContext,
    SubscriptionResponseMessage,
)

from rig.local_pubsub import GreengrassLocalPubSub, InMemoryLocalPubSub


class FakeGreengrassIpcClient:
    def __init__(self) -> None:
        self.on_stream_event = None
        self.closed = False

    def publish_to_topic(self, **_kwargs: object) -> object:
        return object()

    def subscribe_to_topic(self, **kwargs: object) -> object:
        self.on_stream_event = kwargs["on_stream_event"]
        return object(), FakeGreengrassIpcOperation()

    def close(self) -> object:
        self.closed = True
        return object()


class FakeGreengrassIpcOperation:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> object:
        self.closed = True
        return object()


class InMemoryLocalPubSubTests(unittest.TestCase):
    def test_publish_delivers_to_exact_and_wildcard_subscribers(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            bus = InMemoryLocalPubSub()
            received: list[tuple[str, bytes]] = []

            async def handler(topic: str, payload: bytes) -> None:
                received.append((topic, payload))

            await bus.subscribe("dev/txing/rig/v1/connectivity/state/+", handler)
            await bus.subscribe("dev/txing/rig/v1/connectivity/state/unit-1", handler)

            await bus.publish(
                "dev/txing/rig/v1/connectivity/state/unit-1",
                "payload",
            )

            return received

        self.assertEqual(
            asyncio.run(exercise()),
            [
                ("dev/txing/rig/v1/connectivity/state/unit-1", b"payload"),
                ("dev/txing/rig/v1/connectivity/state/unit-1", b"payload"),
            ],
        )

    def test_subscription_can_close(self) -> None:
        async def exercise() -> list[bytes]:
            bus = InMemoryLocalPubSub()
            received: list[bytes] = []

            def handler(_topic: str, payload: bytes) -> None:
                received.append(payload)

            subscription = await bus.subscribe("topic/#", handler)
            await bus.publish("topic/a", b"one")
            subscription.close()
            await bus.publish("topic/a", b"two")
            return received

        self.assertEqual(asyncio.run(exercise()), [b"one"])


class GreengrassLocalPubSubTests(unittest.TestCase):
    def test_subscribe_delivers_binary_payload_with_actual_context_topic(self) -> None:
        async def exercise() -> list[tuple[str, bytes]]:
            client = FakeGreengrassIpcClient()
            bus = GreengrassLocalPubSub(client=client)
            received: list[tuple[str, bytes]] = []

            def handler(topic: str, payload: bytes) -> None:
                received.append((topic, payload))

            await bus.subscribe("dev/txing/rig/v1/connectivity/state/+", handler)
            assert client.on_stream_event is not None
            client.on_stream_event(
                SubscriptionResponseMessage(
                    binary_message=BinaryMessage(
                        message=b"payload",
                        context=MessageContext(
                            topic="dev/txing/rig/v1/connectivity/state/unit-1"
                        ),
                    )
                )
            )
            await asyncio.sleep(0)
            return received

        self.assertEqual(
            asyncio.run(exercise()),
            [("dev/txing/rig/v1/connectivity/state/unit-1", b"payload")],
        )

    def test_subscribe_logs_handler_failure(self) -> None:
        async def exercise() -> list[str]:
            client = FakeGreengrassIpcClient()
            bus = GreengrassLocalPubSub(client=client)

            def handler(_topic: str, _payload: bytes) -> None:
                raise RuntimeError("boom")

            await bus.subscribe("dev/txing/rig/v1/connectivity/state/+", handler)
            assert client.on_stream_event is not None
            with self.assertLogs("rig.local_pubsub", level="ERROR") as logs:
                client.on_stream_event(
                    SubscriptionResponseMessage(
                        binary_message=BinaryMessage(
                            message=b"payload",
                            context=MessageContext(
                                topic="dev/txing/rig/v1/connectivity/state/unit-1"
                            ),
                        )
                    )
                )
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            return logs.output

        [log_line] = asyncio.run(exercise())
        self.assertIn("Greengrass local pub/sub handler failed", log_line)
        self.assertIn("dev/txing/rig/v1/connectivity/state/unit-1", log_line)

    def test_subscription_and_client_can_close(self) -> None:
        async def exercise() -> tuple[bool, bool]:
            client = FakeGreengrassIpcClient()
            bus = GreengrassLocalPubSub(client=client)

            subscription = await bus.subscribe("topic/#", lambda _topic, _payload: None)
            operation = subscription.subscription[1]  # type: ignore[attr-defined,index]
            subscription.close()  # type: ignore[attr-defined]
            bus.close()
            return operation.closed, client.closed

        self.assertEqual(asyncio.run(exercise()), (True, True))


if __name__ == "__main__":
    unittest.main()
