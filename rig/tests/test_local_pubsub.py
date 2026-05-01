from __future__ import annotations

import asyncio
import unittest

from rig.local_pubsub import InMemoryLocalPubSub


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


if __name__ == "__main__":
    unittest.main()
