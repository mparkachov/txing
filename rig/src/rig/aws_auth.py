from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any

try:
    import boto3
except ImportError as exc:  # pragma: no cover - exercised in startup validation
    boto3 = None
    BOTO3_IMPORT_ERROR: Exception | None = exc
else:
    BOTO3_IMPORT_ERROR = None

try:
    from awscrt import auth
except ImportError as exc:  # pragma: no cover - exercised in startup validation
    auth = None
    AWS_CRT_IMPORT_ERROR: Exception | None = exc
else:
    AWS_CRT_IMPORT_ERROR = None

AWS_IOT_DATA_ENDPOINT_TYPE = "iot:Data-ATS"


def resolve_aws_region() -> str | None:
    for env_name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        region = os.getenv(env_name, "").strip()
        if region:
            return region
    if boto3 is not None:
        return boto3.session.Session().region_name
    return None


def _normalize_iot_endpoint_address(endpoint_address: Any) -> str:
    if not isinstance(endpoint_address, str):
        raise RuntimeError(
            "AWS IoT DescribeEndpoint did not return a valid endpointAddress"
        )
    endpoint = endpoint_address.strip()
    if not endpoint:
        raise RuntimeError("AWS IoT DescribeEndpoint returned an empty endpointAddress")
    return endpoint


@dataclass(slots=True, frozen=True)
class AwsCredentialSnapshot:
    access_key_id: str
    secret_access_key: str
    session_token: str | None
    expiration: datetime | None = None


def _normalize_expiration(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def freeze_session_credentials(session: Any) -> AwsCredentialSnapshot:
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError(
            "AWS credentials were not found in the default SDK chain. "
            "Configure AWS_PROFILE or another standard AWS credential source."
        )

    frozen = credentials.get_frozen_credentials()
    access_key_id = getattr(frozen, "access_key", None) or getattr(
        frozen,
        "access_key_id",
        None,
    )
    secret_access_key = getattr(frozen, "secret_key", None) or getattr(
        frozen,
        "secret_access_key",
        None,
    )
    session_token = getattr(frozen, "token", None) or getattr(
        frozen,
        "session_token",
        None,
    )
    if not access_key_id or not secret_access_key:
        raise RuntimeError("AWS credentials are present but incomplete")

    return AwsCredentialSnapshot(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
        expiration=_normalize_expiration(
            getattr(credentials, "_expiry_time", None)
            or getattr(credentials, "expiry_time", None)
        ),
    )


class AwsCredentialsBridge:
    def __init__(self, session: Any) -> None:
        self._session = session
        self._provider: Any | None = None

    def snapshot(self) -> AwsCredentialSnapshot:
        return freeze_session_credentials(self._session)

    def _get_awscrt_credentials(self) -> Any:
        if auth is None:
            raise RuntimeError(
                "awscrt is required for SigV4-authenticated MQTT over WebSockets"
            ) from AWS_CRT_IMPORT_ERROR
        snapshot = self.snapshot()
        return auth.AwsCredentials(
            snapshot.access_key_id,
            snapshot.secret_access_key,
            session_token=snapshot.session_token,
            expiration=snapshot.expiration,
        )

    def credentials_provider(self) -> Any:
        if auth is None:
            raise RuntimeError(
                "awscrt is required for SigV4-authenticated MQTT over WebSockets"
            ) from AWS_CRT_IMPORT_ERROR
        if self._provider is None:
            self._provider = auth.AwsCredentialsProvider.new_delegate(
                self._get_awscrt_credentials
            )
        return self._provider


@dataclass(slots=True)
class AwsRuntime:
    session: Any
    region_name: str
    _credentials_bridge: AwsCredentialsBridge = field(init=False)
    _iot_data_endpoint: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._credentials_bridge = AwsCredentialsBridge(self.session)

    def client(self, service_name: str, *, region_name: str | None = None) -> Any:
        return self.session.client(service_name, region_name=region_name or self.region_name)

    def iot_client(self, *, region_name: str | None = None) -> Any:
        return self.client("iot", region_name=region_name)

    def logs_client(self, *, region_name: str | None = None) -> Any:
        return self.client("logs", region_name=region_name)

    def sts_client(self, *, region_name: str | None = None) -> Any:
        return self.client("sts", region_name=region_name)

    def iot_data_endpoint(self) -> str:
        if self._iot_data_endpoint is not None:
            return self._iot_data_endpoint
        try:
            response = self.iot_client().describe_endpoint(
                endpointType=AWS_IOT_DATA_ENDPOINT_TYPE
            )
        except Exception as err:
            raise RuntimeError(
                f"failed to discover AWS IoT Data-ATS endpoint: {err}"
            ) from err
        endpoint = _normalize_iot_endpoint_address(response.get("endpointAddress"))
        self._iot_data_endpoint = endpoint
        return endpoint

    def credentials_provider(self) -> Any:
        return self._credentials_bridge.credentials_provider()

    def credential_snapshot(self) -> AwsCredentialSnapshot:
        return self._credentials_bridge.snapshot()


def build_aws_runtime(*, region_name: str) -> AwsRuntime:
    if boto3 is None:
        raise RuntimeError("boto3 is required for AWS API access") from BOTO3_IMPORT_ERROR
    return AwsRuntime(
        session=boto3.session.Session(region_name=region_name),
        region_name=region_name,
    )
