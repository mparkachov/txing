from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable, DefaultDict, Protocol

LOGGER = logging.getLogger("rig.local_pubsub")

MessageHandler = Callable[[str, bytes], Awaitable[None] | None]


class LocalPubSub(Protocol):
    async def publish(self, topic: str, payload: bytes | str) -> None:
        pass

    async def subscribe(self, topic: str, handler: MessageHandler) -> object:
        pass


async def _invoke_handler(handler: MessageHandler, topic: str, payload: bytes) -> None:
    result = handler(topic, payload)
    if inspect.isawaitable(result):
        await result


@dataclass(slots=True)
class _InMemorySubscription:
    bus: InMemoryLocalPubSub
    topic: str
    handler: MessageHandler
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.bus.unsubscribe(self.topic, self.handler)


class InMemoryLocalPubSub:
    def __init__(self) -> None:
        self._handlers: DefaultDict[str, list[MessageHandler]] = defaultdict(list)

    async def publish(self, topic: str, payload: bytes | str) -> None:
        payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        tasks: list[asyncio.Task[None]] = []
        for subscription_topic, handlers in list(self._handlers.items()):
            if not _topic_matches(subscription_topic, topic):
                continue
            for handler in list(handlers):
                tasks.append(asyncio.create_task(_invoke_handler(handler, topic, payload_bytes)))
        if tasks:
            await asyncio.gather(*tasks)

    async def subscribe(self, topic: str, handler: MessageHandler) -> _InMemorySubscription:
        self._handlers[topic].append(handler)
        return _InMemorySubscription(self, topic, handler)

    def unsubscribe(self, topic: str, handler: MessageHandler) -> None:
        handlers = self._handlers.get(topic)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return
        if not handlers:
            self._handlers.pop(topic, None)


class GreengrassLocalPubSub:
    def __init__(self, client: object | None = None) -> None:
        if client is None:
            try:
                from awsiot.greengrasscoreipc.clientv2 import GreengrassCoreIPCClientV2
            except ImportError as err:
                raise RuntimeError(
                    "awsiotsdk with Greengrass IPC support is required for Greengrass components"
                ) from err
            client = GreengrassCoreIPCClientV2()
        self._client = client

    async def publish(self, topic: str, payload: bytes | str) -> None:
        payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        try:
            from awsiot.greengrasscoreipc.model import BinaryMessage, PublishMessage
        except ImportError as err:
            raise RuntimeError("Greengrass IPC model classes are unavailable") from err

        publish_message = PublishMessage(
            binary_message=BinaryMessage(message=payload_bytes)
        )
        result = self._client.publish_to_topic(
            topic=topic,
            publish_message=publish_message,
        )
        if inspect.isawaitable(result):
            await result

    async def subscribe(self, topic: str, handler: MessageHandler) -> object:
        loop = asyncio.get_running_loop()

        def _on_stream_event(event: object) -> None:
            message_topic, payload = _extract_ipc_message(event, default_topic=topic)
            if message_topic is None or payload is None:
                return
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    _invoke_handler(handler, message_topic, payload)
                )
            )

        def _on_stream_error(error: Exception) -> bool:
            LOGGER.warning("Greengrass local pub/sub stream error topic=%s error=%s", topic, error)
            return True

        def _on_stream_closed() -> None:
            LOGGER.info("Greengrass local pub/sub stream closed topic=%s", topic)

        result = self._client.subscribe_to_topic(
            topic=topic,
            on_stream_event=_on_stream_event,
            on_stream_error=_on_stream_error,
            on_stream_closed=_on_stream_closed,
        )
        if inspect.isawaitable(result):
            return await result
        return result


def _extract_ipc_message(
    event: object,
    *,
    default_topic: str,
) -> tuple[str | None, bytes | None]:
    binary_message = getattr(event, "binary_message", None)
    json_message = getattr(event, "json_message", None)
    if binary_message is None and json_message is None:
        message = getattr(event, "message", None)
        binary_message = getattr(message, "binary_message", None)
        json_message = getattr(message, "json_message", None)

    message = binary_message if binary_message is not None else json_message
    if message is None:
        return None, None

    context = getattr(message, "context", None)
    context_topic = getattr(context, "topic", None)
    topic = (
        context_topic
        if isinstance(context_topic, str) and context_topic
        else default_topic
    )

    if binary_message is None:
        payload_object = getattr(json_message, "message", None)
        if payload_object is None:
            return topic, None
        return topic, json.dumps(payload_object, separators=(",", ":")).encode(
            "utf-8"
        )

    payload = getattr(binary_message, "message", None)
    if payload is None:
        return topic, None
    if isinstance(payload, str):
        return topic, payload.encode("utf-8")
    return topic, bytes(payload)


def _topic_matches(subscription: str, topic: str) -> bool:
    if subscription == topic:
        return True
    sub_parts = subscription.split("/")
    topic_parts = topic.split("/")
    for index, sub_part in enumerate(sub_parts):
        if sub_part == "#":
            return index == len(sub_parts) - 1
        if index >= len(topic_parts):
            return False
        if sub_part == "+":
            continue
        if sub_part != topic_parts[index]:
            return False
    return len(sub_parts) == len(topic_parts)
