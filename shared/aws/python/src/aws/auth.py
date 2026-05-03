from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any, Callable, Mapping
import urllib.request

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
AWS_CONTAINER_CREDENTIALS_FULL_URI_ENV = "AWS_CONTAINER_CREDENTIALS_FULL_URI"
AWS_CONTAINER_CREDENTIALS_RELATIVE_URI_ENV = "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
AWS_CONTAINER_AUTHORIZATION_TOKEN_ENV = "AWS_CONTAINER_AUTHORIZATION_TOKEN"
AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE_ENV = "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE"
TXING_CONTAINER_CREDENTIALS_WAIT_SECONDS_ENV = (
    "TXING_AWS_CONTAINER_CREDENTIALS_WAIT_SECONDS"
)
TXING_CONTAINER_CREDENTIALS_WAIT_INTERVAL_SECONDS_ENV = (
    "TXING_AWS_CONTAINER_CREDENTIALS_WAIT_INTERVAL_SECONDS"
)
DEFAULT_CONTAINER_CREDENTIALS_WAIT_SECONDS = 60.0
DEFAULT_CONTAINER_CREDENTIALS_WAIT_INTERVAL_SECONDS = 1.0
DEFAULT_CONTAINER_CREDENTIALS_REQUEST_TIMEOUT_SECONDS = 2.0
ECS_CONTAINER_CREDENTIALS_HOST = "http://169.254.170.2"
LOGGER = logging.getLogger(__name__)


def ensure_aws_profile(*profile_env_names: str) -> str | None:
    profile = os.getenv("AWS_PROFILE", "").strip()
    if profile:
        os.environ.setdefault("AWS_DEFAULT_PROFILE", profile)
        return profile

    for env_name in profile_env_names:
        candidate = os.getenv(env_name, "").strip()
        if not candidate:
            continue
        os.environ["AWS_PROFILE"] = candidate
        os.environ.setdefault("AWS_DEFAULT_PROFILE", candidate)
        return candidate
    return None


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


@dataclass(slots=True, frozen=True)
class AwsContainerCredentialsEndpoint:
    url: str
    authorization_token: str | None = field(default=None, repr=False)


def _env_text(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        LOGGER.warning("Ignoring invalid %s=%r; using %.1f", name, raw_value, default)
        return default
    return max(0.0, value)


def _container_authorization_token(env: Mapping[str, str]) -> str | None:
    token = _env_text(env, AWS_CONTAINER_AUTHORIZATION_TOKEN_ENV)
    if token:
        return token

    token_file = _env_text(env, AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE_ENV)
    if not token_file:
        return None
    try:
        with open(token_file, "r", encoding="utf-8") as file:
            token = file.read().strip()
    except OSError as err:
        raise RuntimeError(
            f"failed to read {AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE_ENV}={token_file}: {err}"
        ) from err
    return token or None


def container_credentials_endpoint_from_env(
    env: Mapping[str, str] | None = None,
) -> AwsContainerCredentialsEndpoint | None:
    env = os.environ if env is None else env
    url = _env_text(env, AWS_CONTAINER_CREDENTIALS_FULL_URI_ENV)
    if not url:
        relative_uri = _env_text(env, AWS_CONTAINER_CREDENTIALS_RELATIVE_URI_ENV)
        if relative_uri:
            if not relative_uri.startswith("/"):
                relative_uri = f"/{relative_uri}"
            url = f"{ECS_CONTAINER_CREDENTIALS_HOST}{relative_uri}"
    if not url:
        return None
    return AwsContainerCredentialsEndpoint(
        url=url,
        authorization_token=_container_authorization_token(env),
    )


def _probe_container_credentials_endpoint(
    endpoint: AwsContainerCredentialsEndpoint,
    *,
    request_timeout_seconds: float,
    opener: Callable[..., Any] | None,
) -> None:
    request = urllib.request.Request(endpoint.url, method="GET")
    if endpoint.authorization_token:
        request.add_header("Authorization", endpoint.authorization_token)
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=request_timeout_seconds) as response:
        response.read(1)


def wait_for_container_credentials_endpoint(
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    interval_seconds: float | None = None,
    request_timeout_seconds: float = DEFAULT_CONTAINER_CREDENTIALS_REQUEST_TIMEOUT_SECONDS,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> bool:
    endpoint = container_credentials_endpoint_from_env(env)
    if endpoint is None:
        return False

    timeout_seconds = (
        _parse_float_env(
            TXING_CONTAINER_CREDENTIALS_WAIT_SECONDS_ENV,
            DEFAULT_CONTAINER_CREDENTIALS_WAIT_SECONDS,
        )
        if timeout_seconds is None
        else max(0.0, timeout_seconds)
    )
    interval_seconds = (
        _parse_float_env(
            TXING_CONTAINER_CREDENTIALS_WAIT_INTERVAL_SECONDS_ENV,
            DEFAULT_CONTAINER_CREDENTIALS_WAIT_INTERVAL_SECONDS,
        )
        if interval_seconds is None
        else max(0.0, interval_seconds)
    )
    request_timeout_seconds = max(0.1, request_timeout_seconds)
    sleep = sleep or time.sleep
    deadline = time.monotonic() + timeout_seconds
    attempts = 0
    last_error: Exception | None = None

    while True:
        attempts += 1
        try:
            _probe_container_credentials_endpoint(
                endpoint,
                request_timeout_seconds=request_timeout_seconds,
                opener=opener,
            )
            if attempts > 1:
                LOGGER.info(
                    "AWS container credentials endpoint became reachable after %s attempt(s)",
                    attempts,
                )
            return True
        except Exception as err:
            last_error = err
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if attempts == 1:
                LOGGER.info(
                    "Waiting for AWS container credentials endpoint %s",
                    endpoint.url,
                )
            sleep(min(interval_seconds, remaining))

    raise RuntimeError(
        "AWS container credentials endpoint is not reachable after "
        f"{timeout_seconds:.1f}s ({endpoint.url}): {last_error}"
    ) from last_error


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
        wait_for_container_credentials_endpoint()
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
    iot_data_endpoint_override: str | None = None
    _credentials_bridge: AwsCredentialsBridge = field(init=False)
    _iot_data_endpoint: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._credentials_bridge = AwsCredentialsBridge(self.session)
        if self.iot_data_endpoint_override is not None:
            self._iot_data_endpoint = _normalize_iot_endpoint_address(
                self.iot_data_endpoint_override
            )

    def client(
        self,
        service_name: str,
        *,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        wait_for_container_credentials_endpoint()
        return self.session.client(
            service_name,
            region_name=region_name or self.region_name,
            **kwargs,
        )

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


def build_aws_runtime(
    *,
    region_name: str,
    iot_data_endpoint: str | None = None,
) -> AwsRuntime:
    if boto3 is None:
        raise RuntimeError("boto3 is required for AWS API access") from BOTO3_IMPORT_ERROR
    return AwsRuntime(
        session=boto3.session.Session(region_name=region_name),
        region_name=region_name,
        iot_data_endpoint_override=iot_data_endpoint,
    )
