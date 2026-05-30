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
    def __init__(self, payload: bytes | None = None) -> None:
        self._payload = payload or (
            b'{'
            b'"AccessKeyId": "AKIA", '
            b'"SecretAccessKey": "secret", '
            b'"Token": "token", '
            b'"Expiration": "2026-05-03T22:00:00Z"'
            b'}'
        )

    def __enter__(self) -> "_FakeCredentialsEndpointResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self._payload


class _CredentialsEndpointProbe:
    def __init__(self, *, failures: int = 0, payload: bytes | None = None) -> None:
        self.failures = failures
        self.payload = payload
        self.requests = []
        self.timeouts: list[float] = []

    def __call__(self, request, *, timeout: float):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.failures:
            self.failures -= 1
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        return _FakeCredentialsEndpointResponse(self.payload)


class AwsAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(os.environ, {}, clear=True)
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

    def test_freeze_session_credentials_reads_current_boto3_values(self) -> None:
        session = _RotatingSession()

        first = aws_auth.freeze_session_credentials(session)
        second = aws_auth.freeze_session_credentials(session)

        self.assertEqual(first.access_key_id, "AKIA1")
        self.assertEqual(second.access_key_id, "AKIA2")
        self.assertEqual(first.session_token, "token-1")
        self.assertEqual(second.session_token, "token-2")
        self.assertIsNotNone(second.expiration)

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

        with self.assertRaisesRegex(RuntimeError, "did not return credentials"):
            aws_auth.wait_for_container_credentials_endpoint(
                env={
                    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
                },
                timeout_seconds=0,
                opener=probe,
            )

    def test_fetch_container_credentials_snapshot_reads_nested_payload(self) -> None:
        probe = _CredentialsEndpointProbe(
            payload=(
                b'{'
                b'"credentials": {'
                b'"accessKeyId": "AKIA2", '
                b'"secretAccessKey": "secret-2", '
                b'"sessionToken": "token-2", '
                b'"expiration": "2026-05-03T22:00:00Z"'
                b'}'
                b'}'
            )
        )

        snapshot = aws_auth.fetch_container_credentials_snapshot(
            env={
                "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:1234/creds",
            },
            timeout_seconds=0,
            opener=probe,
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.access_key_id, "AKIA2")
        self.assertEqual(snapshot.secret_access_key, "secret-2")
        self.assertEqual(snapshot.session_token, "token-2")
        self.assertEqual(
            snapshot.expiration,
            datetime(2026, 5, 3, 22, 0, tzinfo=timezone.utc),
        )

    def test_runtime_client_injects_container_credentials_snapshot(self) -> None:
        client = _FakeIotClient({"endpointAddress": "unused.iot.eu-central-1.amazonaws.com"})
        session = _FakeEndpointSession(client)
        runtime = aws_auth.AwsRuntime(session=session, region_name="eu-central-1")
        snapshot = aws_auth.AwsCredentialSnapshot(
            access_key_id="AKIA",
            secret_access_key="secret",
            session_token="token",
        )

        with patch.object(
            aws_auth,
            "fetch_container_credentials_snapshot",
            return_value=snapshot,
        ):
            runtime.client("iot")

        self.assertEqual(
            session.last_client_request,
            (
                "iot",
                "eu-central-1",
                {
                    "aws_access_key_id": "AKIA",
                    "aws_secret_access_key": "secret",
                    "aws_session_token": "token",
                },
            ),
        )

    def test_runtime_client_preserves_explicit_credentials(self) -> None:
        client = _FakeIotClient({"endpointAddress": "unused.iot.eu-central-1.amazonaws.com"})
        session = _FakeEndpointSession(client)
        runtime = aws_auth.AwsRuntime(session=session, region_name="eu-central-1")
        snapshot = aws_auth.AwsCredentialSnapshot(
            access_key_id="AKIA",
            secret_access_key="secret",
            session_token="token",
        )

        with patch.object(
            aws_auth,
            "fetch_container_credentials_snapshot",
            return_value=snapshot,
        ):
            runtime.client(
                "iot",
                aws_access_key_id="manual",
                aws_secret_access_key="manual-secret",
            )

        self.assertEqual(
            session.last_client_request,
            (
                "iot",
                "eu-central-1",
                {
                    "aws_access_key_id": "manual",
                    "aws_secret_access_key": "manual-secret",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
