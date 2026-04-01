from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import rig.aws_auth as aws_auth


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


if __name__ == "__main__":
    unittest.main()
