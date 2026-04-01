from __future__ import annotations

import unittest

from rig.aws_mqtt import AwsIotWebsocketConnection


class AwsMqttCallbackTests(unittest.TestCase):
    def test_lifecycle_callbacks_accept_keyword_arguments(self) -> None:
        interrupted_errors: list[Exception] = []
        resumed_events: list[tuple[object, bool]] = []
        success_events: list[object] = []
        failure_events: list[object] = []
        closed_events: list[object] = []

        connection = object.__new__(AwsIotWebsocketConnection)
        connection._on_connection_interrupted_callback = interrupted_errors.append
        connection._on_connection_resumed_callback = (
            lambda return_code, session_present: resumed_events.append(
                (return_code, session_present)
            )
        )
        connection._on_connection_success_callback = success_events.append
        connection._on_connection_failure_callback = failure_events.append
        connection._on_connection_closed_callback = closed_events.append

        callback_data = object()
        interrupted_error = RuntimeError("interrupted")

        connection._on_connection_interrupted(
            connection=object(),
            error=interrupted_error,
        )
        connection._on_connection_resumed(
            connection=object(),
            return_code="ACCEPTED",
            session_present=False,
        )
        connection._on_connection_success(
            connection=object(),
            callback_data=callback_data,
        )
        connection._on_connection_failure(
            connection=object(),
            callback_data=callback_data,
        )
        connection._on_connection_closed(
            connection=object(),
            callback_data=callback_data,
        )

        self.assertEqual(interrupted_errors, [interrupted_error])
        self.assertEqual(resumed_events, [("ACCEPTED", False)])
        self.assertEqual(success_events, [callback_data])
        self.assertEqual(failure_events, [callback_data])
        self.assertEqual(closed_events, [callback_data])
