from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from .aws_auth import AwsRuntime

try:
    from awscrt import mqtt
    from awsiot import mqtt_connection_builder
except ImportError as exc:  # pragma: no cover - exercised in startup validation
    mqtt = None
    mqtt_connection_builder = None
    AWS_IOT_SDK_IMPORT_ERROR: Exception | None = exc
else:
    AWS_IOT_SDK_IMPORT_ERROR = None


MessageCallback = Callable[[str, bytes], None]
ConnectionInterruptedCallback = Callable[[Exception], None]
ConnectionResumedCallback = Callable[[Any, bool], None]
ConnectionSuccessCallback = Callable[[Any], None]
ConnectionFailureCallback = Callable[[Any], None]
ConnectionClosedCallback = Callable[[Any], None]


def _ensure_sdk_available() -> None:
    if mqtt is None or mqtt_connection_builder is None:
        raise RuntimeError(
            "awsiotsdk is required for SigV4-authenticated MQTT over WebSockets"
        ) from AWS_IOT_SDK_IMPORT_ERROR


async def _await_future(
    future: Future[Any],
    *,
    timeout_seconds: float | None,
) -> Any:
    return await asyncio.wait_for(
        asyncio.wrap_future(future),
        timeout=timeout_seconds,
    )


@dataclass(slots=True, frozen=True)
class AwsMqttConnectionConfig:
    endpoint: str
    client_id: str
    region_name: str
    connect_timeout_seconds: float
    operation_timeout_seconds: float
    reconnect_min_timeout_seconds: int = 1
    reconnect_max_timeout_seconds: int = 30
    keep_alive_seconds: int = 60


class AwsIotWebsocketConnection:
    def __init__(
        self,
        config: AwsMqttConnectionConfig,
        *,
        aws_runtime: AwsRuntime,
        on_connection_interrupted: ConnectionInterruptedCallback | None = None,
        on_connection_resumed: ConnectionResumedCallback | None = None,
        on_connection_success: ConnectionSuccessCallback | None = None,
        on_connection_failure: ConnectionFailureCallback | None = None,
        on_connection_closed: ConnectionClosedCallback | None = None,
    ) -> None:
        _ensure_sdk_available()

        self._config = config
        self._on_connection_interrupted_callback = on_connection_interrupted
        self._on_connection_resumed_callback = on_connection_resumed
        self._on_connection_success_callback = on_connection_success
        self._on_connection_failure_callback = on_connection_failure
        self._on_connection_closed_callback = on_connection_closed

        self._connection = mqtt_connection_builder.websockets_with_default_aws_signing(
            region=config.region_name,
            credentials_provider=aws_runtime.credentials_provider(),
            endpoint=config.endpoint,
            client_id=config.client_id,
            port=443,
            clean_session=True,
            reconnect_min_timeout_secs=config.reconnect_min_timeout_seconds,
            reconnect_max_timeout_secs=config.reconnect_max_timeout_seconds,
            keep_alive_secs=config.keep_alive_seconds,
            tcp_connect_timeout_ms=max(1, int(config.connect_timeout_seconds * 1000)),
            protocol_operation_timeout_ms=max(
                0,
                int(config.operation_timeout_seconds * 1000),
            ),
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_resumed=self._on_connection_resumed,
            on_connection_success=self._on_connection_success,
            on_connection_failure=self._on_connection_failure,
            on_connection_closed=self._on_connection_closed,
        )

    async def connect(self, *, timeout_seconds: float | None = None) -> Any:
        return await _await_future(
            self._connection.connect(),
            timeout_seconds=timeout_seconds or self._config.connect_timeout_seconds,
        )

    async def disconnect(self, *, timeout_seconds: float | None = None) -> Any:
        return await _await_future(
            self._connection.disconnect(),
            timeout_seconds=timeout_seconds or self._config.connect_timeout_seconds,
        )

    async def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        publish_future, _packet_id = self._connection.publish(
            topic=topic,
            payload=payload,
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )
        return await _await_future(
            publish_future,
            timeout_seconds=timeout_seconds or self._config.operation_timeout_seconds,
        )

    async def subscribe(
        self,
        topic: str,
        callback: MessageCallback,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        subscribe_future, _packet_id = self._connection.subscribe(
            topic=topic,
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self._wrap_message_callback(callback),
        )
        return await _await_future(
            subscribe_future,
            timeout_seconds=timeout_seconds or self._config.operation_timeout_seconds,
        )

    async def resubscribe_existing_topics(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        resubscribe_future, _packet_id = self._connection.resubscribe_existing_topics()
        return await _await_future(
            resubscribe_future,
            timeout_seconds=timeout_seconds or self._config.operation_timeout_seconds,
        )

    def _on_connection_interrupted(
        self,
        connection: Any = None,
        error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        del connection
        if error is None:
            error = kwargs.get("error")
        if error is None:
            return
        if self._on_connection_interrupted_callback is not None:
            self._on_connection_interrupted_callback(error)

    def _on_connection_resumed(
        self,
        connection: Any = None,
        return_code: Any = None,
        session_present: bool | None = None,
        **kwargs: Any,
    ) -> None:
        del connection
        if return_code is None:
            return_code = kwargs.get("return_code")
        if session_present is None:
            session_present = kwargs.get("session_present")
        if session_present is None:
            return
        if self._on_connection_resumed_callback is not None:
            self._on_connection_resumed_callback(return_code, session_present)

    def _on_connection_success(
        self,
        connection: Any = None,
        callback_data: Any = None,
        **kwargs: Any,
    ) -> None:
        del connection
        if callback_data is None:
            callback_data = kwargs.get("callback_data", kwargs.get("data"))
        if self._on_connection_success_callback is not None:
            self._on_connection_success_callback(callback_data)

    def _on_connection_failure(
        self,
        connection: Any = None,
        callback_data: Any = None,
        **kwargs: Any,
    ) -> None:
        del connection
        if callback_data is None:
            callback_data = kwargs.get("callback_data", kwargs.get("data"))
        if self._on_connection_failure_callback is not None:
            self._on_connection_failure_callback(callback_data)

    def _on_connection_closed(
        self,
        connection: Any = None,
        callback_data: Any = None,
        **kwargs: Any,
    ) -> None:
        del connection
        if callback_data is None:
            callback_data = kwargs.get("callback_data", kwargs.get("data"))
        if self._on_connection_closed_callback is not None:
            self._on_connection_closed_callback(callback_data)

    @staticmethod
    def _wrap_message_callback(callback: MessageCallback) -> Callable[..., None]:
        def _wrapped_message_callback(
            topic: str | None = None,
            payload: bytes | bytearray | memoryview | str | None = None,
            **kwargs: Any,
        ) -> None:
            message_topic = topic
            if message_topic is None:
                message_topic = kwargs.get("message_topic")
            if message_topic is None:
                raise TypeError("MQTT message callback missing topic")

            message_payload = payload
            if message_payload is None:
                message_payload = kwargs.get("message_payload")
            if message_payload is None:
                raise TypeError("MQTT message callback missing payload")

            callback(message_topic, bytes(message_payload))

        return _wrapped_message_callback
