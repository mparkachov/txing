from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import urllib.error

from aws import auth as aws_auth


class _FakeFrozenCredentials:
    def __init__(self, access_key: str, secret_key: str, token: str | None) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.token = token


class _FakeCredentials:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        token: str | None,
        expiration: datetime,
    ) -> None:
        self._frozen = _FakeFrozenCredentials(access_key, secret_key, token)
        self._expiry_time = expiration

    def get_frozen_credentials(self) -> _FakeFrozenCredentials:
        return self._frozen


class _RotatingSession:
    def __init__(self) -> None:
        self._counter = 0

    def get_credentials(self) -> _FakeCredentials:
        self._counter += 1
        return _FakeCredentials(
            access_key=f"AKIA{self._counter}",
            secret_key=f"secret-{self._counter}",
            token=f"token-{self._counter}",
            expiration=datetime.now(timezone.utc) + timedelta(minutes=15),
        )


class _FakeAwsCredentials:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None = None,
        expiration: datetime | None = None,
    ) -> None:
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.expiration = expiration


class _FakeCredentialsProvider:
    def __init__(self, get_credentials) -> None:  # type: ignore[no-untyped-def]
        self._get_credentials = get_credentials

    def load(self) -> _FakeAwsCredentials:
        return self._get_credentials()


class _FakeAuthModule:
    AwsCredentials = _FakeAwsCredentials

    class AwsCredentialsProvider:
        @staticmethod
        def new_delegate(get_credentials):  # type: ignore[no-untyped-def]
            return _FakeCredentialsProvider(get_credentials)


class _FakeBoto3Session:
    def __init__(self, region_name: str | None) -> None:
        self.region_name = region_name


class _FakeBoto3Module:
    def __init__(self, region_name: str | None) -> None:
        self.session = self
        self._region_name = region_name

    def Session(self, region_name: str | None = None) -> _FakeBoto3Session:
        return _FakeBoto3Session(region_name or self._region_name)


class _FakeIotClient:
    def __init__(self, response: dict[str, object]) -> None:
        self._response = response
        self.describe_calls = 0
        self.endpoint_type: str | None = None

    def describe_endpoint(self, *, endpointType: str) -> dict[str, object]:
        self.describe_calls += 1
        self.endpoint_type = endpointType
        return self._response


class _FakeEndpointSession:
    def __init__(self, client: _FakeIotClient) -> None:
        self._client = client
        self.last_client_request: tuple[str, str | None, dict[str, object]] | None = None

    def client(
        self,
        service_name: str,
        region_name: str | None = None,
        **kwargs: object,
    ) -> _FakeIotClient:
        self.last_client_request = (service_name, region_name, kwargs)
        return self._client


class _FakeCredentialsEndpointResponse:
    def __enter__(self) -> "_FakeCredentialsEndpointResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return b'{ "AccessKeyId": "AKIA" }'


class _CredentialsEndpointProbe:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.requests = []
        self.timeouts: list[float] = []

    def __call__(self, request, *, timeout: float):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.failures:
            self.failures -= 1
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        return _FakeCredentialsEndpointResponse()


class AwsAuthTests(unittest.TestCase):
    def test_freeze_session_credentials_reads_current_boto3_values(self) -> None:
        session = _RotatingSession()

        first = aws_auth.freeze_session_credentials(session)
        second = aws_auth.freeze_session_credentials(session)

        self.assertEqual(first.access_key_id, "AKIA1")
        self.assertEqual(second.access_key_id, "AKIA2")
        self.assertEqual(first.session_token, "token-1")
        self.assertEqual(second.session_token, "token-2")
        self.assertIsNotNone(second.expiration)

    def test_credentials_bridge_delegates_to_latest_sdk_credentials(self) -> None:
        session = _RotatingSession()
        bridge = aws_auth.AwsCredentialsBridge(session)

        with patch.object(aws_auth, "auth", _FakeAuthModule):
            provider = bridge.credentials_provider()
            first = provider.load()
            second = provider.load()

        self.assertEqual(first.access_key_id, "AKIA1")
        self.assertEqual(first.secret_access_key, "secret-1")
        self.assertEqual(second.access_key_id, "AKIA2")
        self.assertEqual(second.secret_access_key, "secret-2")

    def test_resolve_aws_region_uses_sdk_defaults_without_endpoint_input(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(aws_auth, "boto3", _FakeBoto3Module("eu-central-1")):
                self.assertEqual(aws_auth.resolve_aws_region(), "eu-central-1")

    def test_iot_data_endpoint_discovers_and_caches_endpoint(self) -> None:
        client = _FakeIotClient({"endpointAddress": "abc123-ats.iot.eu-central-1.amazonaws.com"})
        session = _FakeEndpointSession(client)
        runtime = aws_auth.AwsRuntime(session=session, region_name="eu-central-1")

        first = runtime.iot_data_endpoint()
        second = runtime.iot_data_endpoint()

        self.assertEqual(first, "abc123-ats.iot.eu-central-1.amazonaws.com")
        self.assertEqual(second, first)
        self.assertEqual(client.describe_calls, 1)
        self.assertEqual(client.endpoint_type, aws_auth.AWS_IOT_DATA_ENDPOINT_TYPE)
        self.assertEqual(session.last_client_request, ("iot", "eu-central-1", {}))

    def test_iot_data_endpoint_uses_override_without_describe_endpoint(self) -> None:
        client = _FakeIotClient({"endpointAddress": "unused.iot.eu-central-1.amazonaws.com"})
        runtime = aws_auth.AwsRuntime(
            session=_FakeEndpointSession(client),
            region_name="eu-central-1",
            iot_data_endpoint_override="abc123-ats.iot.eu-central-1.amazonaws.com",
        )

        self.assertEqual(
            runtime.iot_data_endpoint(),
            "abc123-ats.iot.eu-central-1.amazonaws.com",
        )
        self.assertEqual(client.describe_calls, 0)

    def test_iot_data_endpoint_rejects_missing_endpoint_address(self) -> None:
        runtime = aws_auth.AwsRuntime(
            session=_FakeEndpointSession(_FakeIotClient({})),
            region_name="eu-central-1",
        )

        with self.assertRaisesRegex(RuntimeError, "endpointAddress"):
            runtime.iot_data_endpoint()

    def test_iot_data_endpoint_rejects_empty_endpoint_address(self) -> None:
        runtime = aws_auth.AwsRuntime(
            session=_FakeEndpointSession(_FakeIotClient({"endpointAddress": "   "})),
            region_name="eu-central-1",
        )

        with self.assertRaisesRegex(RuntimeError, "empty endpointAddress"):
            runtime.iot_data_endpoint()

    def test_container_credentials_wait_noops_without_endpoint_env(self) -> None:
        probe = _CredentialsEndpointProbe()

        ready = aws_auth.wait_for_container_credentials_endpoint(
            env={},
            opener=probe,
        )

        self.assertFalse(ready)
        self.assertEqual(probe.requests, [])

    def test_container_credentials_wait_sends_authorization_token(self) -> None:
        probe = _CredentialsEndpointProbe()

        ready = aws_auth.wait_for_container_credentials_endpoint(
            env={
                "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
                "AWS_CONTAINER_AUTHORIZATION_TOKEN": "Bearer token",
            },
            timeout_seconds=0,
            opener=probe,
        )

        self.assertTrue(ready)
        self.assertEqual(len(probe.requests), 1)
        request = probe.requests[0]
        self.assertEqual(request.full_url, "http://localhost:1234/creds")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")

    def test_container_credentials_wait_reads_authorization_token_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            token_file = os.path.join(temp_dir, "token")
            with open(token_file, "w", encoding="utf-8") as file:
                file.write("TokenFromFile\n")
            probe = _CredentialsEndpointProbe()

            ready = aws_auth.wait_for_container_credentials_endpoint(
                env={
                    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
                    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE": token_file,
                },
                timeout_seconds=0,
                opener=probe,
            )

        self.assertTrue(ready)
        self.assertEqual(probe.requests[0].get_header("Authorization"), "TokenFromFile")

    def test_container_credentials_wait_retries_connection_refused(self) -> None:
        probe = _CredentialsEndpointProbe(failures=2)
        sleeps: list[float] = []

        ready = aws_auth.wait_for_container_credentials_endpoint(
            env={
                "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
            },
            timeout_seconds=5,
            interval_seconds=0.25,
            opener=probe,
            sleep=sleeps.append,
        )

        self.assertTrue(ready)
        self.assertEqual(len(probe.requests), 3)
        self.assertEqual(sleeps, [0.25, 0.25])

    def test_container_credentials_wait_raises_after_timeout(self) -> None:
        probe = _CredentialsEndpointProbe(failures=1)

        with self.assertRaisesRegex(RuntimeError, "not reachable"):
            aws_auth.wait_for_container_credentials_endpoint(
                env={
                    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
                },
                timeout_seconds=0,
                opener=probe,
            )

    def test_runtime_client_waits_for_container_credentials_endpoint(self) -> None:
        client = _FakeIotClient({"endpointAddress": "unused.iot.eu-central-1.amazonaws.com"})
        runtime = aws_auth.AwsRuntime(
            session=_FakeEndpointSession(client),
            region_name="eu-central-1",
        )
        waits = []

        def fake_wait() -> bool:
            waits.append(True)
            return True

        with patch.object(aws_auth, "wait_for_container_credentials_endpoint", fake_wait):
            runtime.client("iot")

        self.assertEqual(waits, [True])


if __name__ == "__main__":
    unittest.main()
