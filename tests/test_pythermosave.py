"""Tests for the vendored pythermosave client."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from urllib.parse import quote

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.thermosave.pythermosave import (
    AuthSession,
    DeviceConfig,
    ScheduleWindow,
    ThermosaveApiError,
    ThermosaveAuthenticationError,
    ThermosaveClient,
    ThermosaveConnectionError,
    ThermosaveInvalidCodeError,
    ThermosaveMode,
    TokenSet,
    UnitInfo,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from freezegun.api import FrozenDateTimeFactory

EMAIL = "user@example.com"
MAC = "aa:bb:cc:dd:ee:ff"
OTHER_MAC = "11:22:33:44:55:66"
COGNITO_URL = "https://cognito.test/"
API_URL = "https://api.test"
DEVICES_PATH = "/v1/devices"
CLAIM_PATH = "/v1/devices/claim"
STATUS_PATH = f"/v1/devices/{quote(MAC, safe='')}/status"
CONFIG_PATH = f"/v1/devices/{quote(MAC, safe='')}/config"
CONFIG_PAYLOAD = {
    "timezone": "Europe/Oslo",
    "windows": [{"start": "17:00", "end": "19:00"}],
    "mode": "auto",
}
CONFIG = DeviceConfig(
    timezone="Europe/Oslo",
    windows=(ScheduleWindow(start="17:00", end="19:00"),),
    mode="auto",
    raw=CONFIG_PAYLOAD,
)
REFRESHED = {"AuthenticationResult": {"AccessToken": "new", "ExpiresIn": 3600}}


class MockBackend:
    """
    Queue responses per endpoint on top of the Home Assistant aiohttp mocker.

    The mocker answers every request to a URL with the same response, and all
    Cognito actions share one URL, so responses are queued per method, URL and
    Cognito action instead.
    """

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        """Initialize the backend."""
        self._aioclient_mock = aioclient_mock
        self._registered: set[tuple[str, str]] = set()
        self._responses: dict[
            tuple[str, str, str | None], list[AiohttpClientMockResponse]
        ] = {}

    def cognito(
        self,
        action: str,
        *,
        status: int = HTTPStatus.OK,
        json: Any = None,
    ) -> None:
        """Queue a Cognito response for an action."""
        self._add("POST", COGNITO_URL, action, status=status, json=json or {})

    def api(
        self,
        method: str,
        path: str,
        *,
        status: int = HTTPStatus.OK,
        json: Any = None,
        text: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Queue a ThermoSave API response."""
        self._add(
            method,
            f"{API_URL}{path}",
            None,
            status=status,
            json=json,
            text=text,
            exc=exc,
        )

    def cognito_payloads(self, action: str) -> list[Any]:
        """Return the payloads sent for a Cognito action."""
        return [
            data
            for _, _, data, headers in self._aioclient_mock.mock_calls
            if headers.get("X-Amz-Target", "").endswith(f".{action}")
        ]

    def api_calls(self) -> list[tuple[str, Any, dict[str, str]]]:
        """Return method, payload and headers of API requests."""
        return [
            (method, data, headers)
            for method, url, data, headers in self._aioclient_mock.mock_calls
            if url.host == URL(API_URL).host
        ]

    def _add(
        self,
        method: str,
        url: str,
        action: str | None,
        **response: Any,
    ) -> None:
        normalized = str(URL(url))
        if (method, normalized) not in self._registered:
            self._aioclient_mock.request(method, url, side_effect=self._respond)
            self._registered.add((method, normalized))
        self._responses.setdefault((method, normalized, action), []).append(
            AiohttpClientMockResponse(method, URL(url), **response)
        )

    async def _respond(
        self, method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        # Yield like a real request would, so concurrent callers interleave.
        await asyncio.sleep(0)
        # The mocker records the call, headers included, before this runs.
        target = self._aioclient_mock.mock_calls[-1][3].get("X-Amz-Target")
        action = target.rsplit(".", 1)[-1] if target else None
        return self._responses[(method.upper(), str(url), action)].pop(0)


@pytest.fixture
def backend(aioclient_mock: AiohttpClientMocker) -> MockBackend:
    """Return the mocked Cognito and ThermoSave backend."""
    return MockBackend(aioclient_mock)


@pytest.fixture
async def session(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncGenerator[aiohttp.ClientSession]:
    """Return a client session bound to the aiohttp mocker."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield session
    await session.close()


def _client(session: aiohttp.ClientSession, **kwargs: Any) -> ThermosaveClient:
    return ThermosaveClient(
        session,
        cognito_client_id=" client-id ",
        cognito_base_url=COGNITO_URL,
        api_base_url=f"{API_URL}/",
        **{"access_token": "access", "refresh_token": "refresh", **kwargs},
    )


@pytest.fixture
def client(session: aiohttp.ClientSession) -> ThermosaveClient:
    """Return a client holding tokens without a known expiry."""
    return _client(session)


def _jwt(payload: object) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"header.{encoded.rstrip('=')}.signature"


async def test_init_requires_client_id(session: aiohttp.ClientSession) -> None:
    """Test a blank Cognito client ID is rejected."""
    with pytest.raises(ValueError, match="cognito_client_id"):
        ThermosaveClient(session, cognito_client_id=" ")


async def test_tokens(session: aiohttp.ClientSession) -> None:
    """Test the current tokens are only returned when complete."""
    assert ThermosaveClient(session, cognito_client_id="id").tokens is None
    assert _client(session, expires_at=1.0).tokens == TokenSet("access", "refresh", 1.0)


async def test_login(backend: MockBackend, session: aiohttp.ClientSession) -> None:
    """Test signing up, requesting a code and answering the challenge."""
    store_tokens = AsyncMock()
    client = ThermosaveClient(
        session,
        cognito_client_id="client-id",
        cognito_base_url=COGNITO_URL,
        token_update_callback=store_tokens,
    )
    backend.cognito("SignUp")
    backend.cognito(
        "InitiateAuth", json={"Session": "session", "ChallengeName": "EMAIL_OTP"}
    )
    backend.cognito(
        "RespondToAuthChallenge",
        json={
            "AuthenticationResult": {
                "AccessToken": "access",
                "RefreshToken": "refresh",
                "ExpiresIn": "not a number",
            }
        },
    )

    auth = await client.request_auth_code(" User@Example.com ")
    assert auth == AuthSession(EMAIL, "session")
    assert client.pending_auth == auth

    tokens = await client.authenticate(EMAIL, " 123456 ")
    assert tokens == TokenSet("access", "refresh", None)
    assert client.tokens == tokens
    assert client.pending_auth is None
    store_tokens.assert_awaited_once_with(tokens)

    assert backend.cognito_payloads("SignUp") == [
        {
            "ClientId": "client-id",
            "Username": EMAIL,
            "UserAttributes": [{"Name": "email", "Value": EMAIL}],
        }
    ]
    assert backend.cognito_payloads("InitiateAuth") == [
        {
            "AuthFlow": "USER_AUTH",
            "ClientId": "client-id",
            "AuthParameters": {"USERNAME": EMAIL, "PREFERRED_CHALLENGE": "EMAIL_OTP"},
        }
    ]
    assert backend.cognito_payloads("RespondToAuthChallenge") == [
        {
            "ChallengeName": "EMAIL_OTP",
            "ClientId": "client-id",
            "Session": "session",
            "ChallengeResponses": {"USERNAME": EMAIL, "EMAIL_OTP_CODE": "123456"},
        }
    ]


@pytest.mark.parametrize(
    "error",
    [
        {"__type": "com.amazonaws.cognito#UsernameExistsException"},
        {"code": "UsernameExistsException"},
    ],
)
async def test_request_code_existing_user(
    backend: MockBackend, client: ThermosaveClient, error: dict[str, str]
) -> None:
    """Test an already registered email still gets a code."""
    backend.cognito("SignUp", status=HTTPStatus.BAD_REQUEST, json=error)
    backend.cognito("InitiateAuth", json={"Session": "session"})

    assert await client.request_auth_code(EMAIL) == AuthSession(EMAIL, "session")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ({"__type": "InvalidParameterException", "message": "bad"}, "bad"),
        ({"__type": 5}, "ThermoSave request failed with HTTP 400"),
    ],
)
async def test_request_code_sign_up_error(
    backend: MockBackend,
    client: ThermosaveClient,
    error: dict[str, Any],
    code: str,
) -> None:
    """Test other sign up errors are raised."""
    backend.cognito("SignUp", status=HTTPStatus.BAD_REQUEST, json=error)

    with pytest.raises(ThermosaveApiError, match=code) as err:
        await client.request_auth_code(EMAIL)
    assert err.value.status == HTTPStatus.BAD_REQUEST


async def test_request_code_api_error_code(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test the AWS error code is stored on the raised error."""
    backend.cognito(
        "SignUp",
        status=HTTPStatus.BAD_REQUEST,
        json={"__type": "InvalidParameterException"},
    )

    with pytest.raises(ThermosaveApiError) as err:
        await client.request_auth_code(EMAIL)
    assert err.value.code == "InvalidParameterException"


@pytest.mark.parametrize(
    ("status", "response", "message"),
    [
        (
            HTTPStatus.BAD_REQUEST,
            {"__type": "NotAuthorizedException", "message": "disabled"},
            "disabled",
        ),
        (HTTPStatus.OK, {}, "did not return an email OTP session"),
        (
            HTTPStatus.OK,
            {"Session": "session", "ChallengeName": "SMS_MFA"},
            "unsupported challenge 'SMS_MFA'",
        ),
    ],
)
async def test_request_code_initiate_error(
    backend: MockBackend,
    client: ThermosaveClient,
    status: int,
    response: dict[str, str],
    message: str,
) -> None:
    """Test unusable InitiateAuth responses are authentication errors."""
    backend.cognito("SignUp")
    backend.cognito("InitiateAuth", status=status, json=response)

    with pytest.raises(ThermosaveAuthenticationError, match=message):
        await client.request_auth_code(EMAIL)


async def test_request_code_invalid_email(client: ThermosaveClient) -> None:
    """Test an invalid email is rejected before any request."""
    with pytest.raises(ValueError, match="valid email"):
        await client.request_auth_code("not-an-email")


async def test_authenticate_without_session(client: ThermosaveClient) -> None:
    """Test answering a challenge requires a pending session."""
    with pytest.raises(ThermosaveAuthenticationError, match="No pending"):
        await client.authenticate(EMAIL, "123456")


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("CodeMismatchException", ThermosaveInvalidCodeError),
        ("ExpiredCodeException", ThermosaveInvalidCodeError),
        ("NotAuthorizedException", ThermosaveInvalidCodeError),
        ("TooManyRequestsException", ThermosaveApiError),
    ],
)
async def test_authenticate_error(
    backend: MockBackend,
    client: ThermosaveClient,
    code: str,
    error: type[Exception],
) -> None:
    """Test rejected codes are invalid code errors."""
    backend.cognito(
        "RespondToAuthChallenge", status=HTTPStatus.BAD_REQUEST, json={"__type": code}
    )

    with pytest.raises(error):
        await client.authenticate(EMAIL, "123456", session="session")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "did not contain AuthenticationResult"),
        (
            {"AuthenticationResult": {"RefreshToken": "r"}},
            "did not contain AccessToken",
        ),
        (
            {"AuthenticationResult": {"AccessToken": "a"}},
            "did not contain RefreshToken",
        ),
    ],
)
async def test_authenticate_incomplete_result(
    backend: MockBackend,
    client: ThermosaveClient,
    response: dict[str, Any],
    message: str,
) -> None:
    """Test incomplete authentication results are rejected."""
    backend.cognito("RespondToAuthChallenge", json=response)

    with pytest.raises(ThermosaveAuthenticationError, match=message):
        await client.authenticate(EMAIL, "123456", session="session")


@pytest.mark.parametrize(
    ("result", "expires_in", "expires_at"),
    [
        ({"AccessToken": "token", "ExpiresIn": 3600}, 3600.0, None),
        ({"AccessToken": "token", "ExpiresIn": "60"}, 60.0, None),
        (
            {"AccessToken": _jwt({"exp": 2_000_000_000}), "ExpiresIn": "soon"},
            None,
            2_000_000_000.0,
        ),
        ({"AccessToken": _jwt({"sub": "user"})}, None, None),
        ({"AccessToken": "token"}, None, None),
        ({"AccessToken": "header.bm90IGpzb24.signature"}, None, None),
    ],
)
async def test_token_expiry(
    backend: MockBackend,
    client: ThermosaveClient,
    freezer: FrozenDateTimeFactory,
    result: dict[str, Any],
    expires_in: float | None,
    expires_at: float | None,
) -> None:
    """Test the expiry comes from ExpiresIn, else from the JWT exp claim."""
    backend.cognito(
        "RespondToAuthChallenge",
        json={"AuthenticationResult": {**result, "RefreshToken": "refresh"}},
    )

    tokens = await client.authenticate(EMAIL, "123456", session="session")

    if expires_in is not None:
        expires_at = time.time() + expires_in
    assert tokens.expires_at == expires_at


async def test_refresh_access_token(
    backend: MockBackend,
    session: aiohttp.ClientSession,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a forced refresh keeps the refresh token Cognito did not return."""
    updates: list[TokenSet] = []
    client = _client(session, token_update_callback=updates.append)
    backend.cognito("InitiateAuth", json=REFRESHED)

    tokens = await client.refresh_access_token()

    assert tokens == TokenSet("new", "refresh", time.time() + 3600)
    assert updates == [tokens]
    assert backend.cognito_payloads("InitiateAuth") == [
        {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": "client-id",
            "AuthParameters": {"REFRESH_TOKEN": "refresh"},
        }
    ]


async def test_refresh_without_refresh_token(session: aiohttp.ClientSession) -> None:
    """Test refreshing requires a refresh token."""
    client = _client(session, refresh_token=None)

    with pytest.raises(ThermosaveAuthenticationError, match="No refresh token"):
        await client.refresh_access_token()


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        (
            HTTPStatus.BAD_REQUEST,
            "NotAuthorizedException",
            ThermosaveAuthenticationError,
        ),
        (
            HTTPStatus.BAD_REQUEST,
            "UserNotFoundException",
            ThermosaveAuthenticationError,
        ),
        (
            HTTPStatus.BAD_REQUEST,
            "InvalidParameterException",
            ThermosaveAuthenticationError,
        ),
        (
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "InternalErrorException",
            ThermosaveApiError,
        ),
    ],
)
async def test_refresh_error(
    backend: MockBackend,
    client: ThermosaveClient,
    status: int,
    code: str,
    error: type[Exception],
) -> None:
    """Test revoked refresh tokens are authentication errors."""
    backend.cognito("InitiateAuth", status=status, json={"__type": code})

    with pytest.raises(error):
        await client.refresh_access_token()


async def test_request_refreshes_on_unauthorized(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test a rejected access token is refreshed and the request retried."""
    backend.api("GET", DEVICES_PATH, status=HTTPStatus.UNAUTHORIZED)
    backend.api("GET", DEVICES_PATH, json={"devices": [MAC]})
    backend.cognito("InitiateAuth", json=REFRESHED)

    assert await client.list_devices() == (MAC,)

    assert [headers["Authorization"] for *_, headers in backend.api_calls()] == [
        "Bearer access",
        "Bearer new",
    ]


async def test_request_refreshes_expired_token(
    backend: MockBackend,
    session: aiohttp.ClientSession,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an expired access token is refreshed once before requests."""
    client = _client(session, expires_at=time.time() - 60)
    backend.api("GET", DEVICES_PATH, json={"devices": [MAC]})
    backend.api("GET", DEVICES_PATH, json={"devices": [MAC]})
    backend.cognito("InitiateAuth", json=REFRESHED)

    await asyncio.gather(client.list_devices(), client.list_devices())

    assert len(backend.cognito_payloads("InitiateAuth")) == 1
    assert [headers["Authorization"] for *_, headers in backend.api_calls()] == [
        "Bearer new",
        "Bearer new",
    ]


async def test_request_without_access_token(session: aiohttp.ClientSession) -> None:
    """Test API requests require an access token."""
    client = _client(session, access_token=None)

    with pytest.raises(ThermosaveAuthenticationError, match="No access token"):
        await client.list_devices()


@pytest.mark.parametrize("exc", [aiohttp.ClientError("boom"), TimeoutError()])
async def test_request_connection_error(
    backend: MockBackend, client: ThermosaveClient, exc: Exception
) -> None:
    """Test transport errors are connection errors."""
    backend.api("GET", DEVICES_PATH, exc=exc)

    with pytest.raises(ThermosaveConnectionError):
        await client.list_devices()


@pytest.mark.parametrize(
    ("status", "response", "error", "message"),
    [
        (HTTPStatus.NOT_FOUND, {"message": "gone"}, ThermosaveApiError, "gone"),
        (HTTPStatus.NOT_FOUND, {"Message": "gone"}, ThermosaveApiError, "gone"),
        (HTTPStatus.NOT_FOUND, {"error": "gone"}, ThermosaveApiError, "gone"),
        (HTTPStatus.NOT_FOUND, {"detail": "gone"}, ThermosaveApiError, "gone"),
        (HTTPStatus.NOT_FOUND, {"message": ""}, ThermosaveApiError, "HTTP 404"),
        (HTTPStatus.FORBIDDEN, {}, ThermosaveAuthenticationError, "HTTP 403"),
        (HTTPStatus.BAD_GATEWAY, {}, ThermosaveConnectionError, "HTTP 502"),
        (HTTPStatus.OK, {"devices": "aa:bb"}, ThermosaveApiError, "did not contain"),
        (HTTPStatus.OK, [MAC], ThermosaveApiError, "did not contain"),
    ],
)
async def test_list_devices_error(
    backend: MockBackend,
    client: ThermosaveClient,
    status: int,
    response: Any,
    error: type[Exception],
    message: str,
) -> None:
    """Test failed or malformed device list responses."""
    backend.api("GET", DEVICES_PATH, status=status, json=response)

    with pytest.raises(error, match=message):
        await client.list_devices()


@pytest.mark.parametrize(
    ("status", "text", "error", "message"),
    [
        (HTTPStatus.SERVICE_UNAVAILABLE, "Try later", ThermosaveConnectionError, "Try"),
        (HTTPStatus.BAD_REQUEST, "", ThermosaveApiError, "HTTP 400"),
    ],
)
async def test_non_json_response(
    backend: MockBackend,
    client: ThermosaveClient,
    status: int,
    text: str,
    error: type[Exception],
    message: str,
) -> None:
    """Test a non-JSON body is used as the error message."""
    backend.api("GET", DEVICES_PATH, status=status, text=text)

    with pytest.raises(error, match=message):
        await client.list_devices()


async def test_list_devices(backend: MockBackend, client: ThermosaveClient) -> None:
    """Test device MACs are normalized and deduplicated."""
    backend.api(
        "GET",
        DEVICES_PATH,
        json={"devices": ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", 5, OTHER_MAC]},
    )

    assert await client.list_devices() == (MAC, OTHER_MAC)


@pytest.mark.parametrize("status", [HTTPStatus.OK, HTTPStatus.NO_CONTENT])
async def test_claim_device(
    backend: MockBackend, client: ThermosaveClient, status: int
) -> None:
    """Test claiming a device."""
    backend.api("POST", CLAIM_PATH, status=status)

    await client.claim_device("AA-BB-CC-DD-EE-FF", "nonce", "signature")

    assert backend.api_calls()[0][:2] == (
        "POST",
        {"mac": MAC, "nonce": "nonce", "signature": "signature"},
    )


async def test_claim_device_error(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test a rejected claim is raised."""
    backend.api("POST", CLAIM_PATH, status=HTTPStatus.CONFLICT, json={"message": "no"})

    with pytest.raises(ThermosaveApiError, match="no") as err:
        await client.claim_device(MAC, "nonce", "signature")
    assert err.value.status == HTTPStatus.CONFLICT


async def test_invalid_mac(client: ThermosaveClient) -> None:
    """Test invalid MAC addresses are rejected before any request."""
    with pytest.raises(ValueError, match="Invalid MAC address"):
        await client.get_device_status("not-a-mac")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "id": "AA-BB-CC-DD-EE-FF",
                "connection": {
                    "state": "online",
                    "lastSeen": "2026-10-23T12:00:00+00:00",
                },
                "power": {"kW": "2.5"},
                "mode": "auto",
                "relay": {"state": " ON "},
            },
            {
                "connection_state": "online",
                "last_seen": datetime(2026, 10, 23, 12, tzinfo=UTC),
                "power_kw": 2.5,
                "mode": "auto",
                "relay_state": True,
            },
        ),
        (
            {
                "connection": "online",
                "power": {"kW": "lots"},
                "mode": "",
                "relay": {"state": "off"},
            },
            {
                "connection_state": None,
                "last_seen": None,
                "power_kw": None,
                "mode": None,
                "relay_state": False,
            },
        ),
        (
            {
                "connection": {"state": "offline", "lastSeen": "yesterday"},
                "power": {"kW": None},
                "relay": {"state": "flickering"},
            },
            {
                "connection_state": "offline",
                "last_seen": None,
                "power_kw": None,
                "mode": None,
                "relay_state": None,
            },
        ),
        (
            {
                "connection": {"lastSeen": 1_700_000_000},
                "power": {"kW": [1]},
                "relay": {"state": 1},
            },
            {
                "connection_state": None,
                "last_seen": None,
                "power_kw": None,
                "mode": None,
                "relay_state": None,
            },
        ),
    ],
)
async def test_get_device_status(
    backend: MockBackend,
    client: ThermosaveClient,
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """Test device status parsing tolerates missing or malformed fields."""
    backend.api("GET", STATUS_PATH, json=payload)

    status = await client.get_device_status(MAC)

    assert status is not None
    assert status.mac == MAC
    assert status.raw == payload
    assert {key: getattr(status, key) for key in expected} == expected


async def test_get_device_status_unavailable(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test a device without status returns None."""
    backend.api("GET", STATUS_PATH, status=HTTPStatus.NOT_FOUND)

    assert await client.get_device_status(MAC) is None


@pytest.mark.parametrize(
    ("windows", "expected"),
    [
        (
            [
                {"start": "17:00", "end": "19:00"},
                "22:00-06:00",
                {"start": "22:00"},
                {"start": 1, "end": "06:00"},
            ],
            (ScheduleWindow(start="17:00", end="19:00"),),
        ),
        ("17:00-19:00", ()),
        (None, ()),
    ],
)
async def test_get_device_config(
    backend: MockBackend,
    client: ThermosaveClient,
    windows: Any,
    expected: tuple[ScheduleWindow, ...],
) -> None:
    """Test malformed schedule windows are skipped."""
    backend.api(
        "GET", CONFIG_PATH, json={"timezone": "UTC", "mode": "on", "windows": windows}
    )

    config = await client.get_device_config(MAC)

    assert config is not None
    assert config.windows == expected
    assert config.timezone == "UTC"
    assert config.mode == ThermosaveMode.ON


@pytest.mark.parametrize("status", [HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND])
async def test_get_device_config_missing(
    backend: MockBackend, client: ThermosaveClient, status: int
) -> None:
    """Test a device without config returns None."""
    backend.api("GET", CONFIG_PATH, status=status)

    assert await client.get_device_config(MAC) is None


async def test_get_device_config_error(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test other config errors are raised."""
    backend.api("GET", CONFIG_PATH, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    with pytest.raises(ThermosaveConnectionError):
        await client.get_device_config(MAC)


async def test_read_info(backend: MockBackend, client: ThermosaveClient) -> None:
    """Test reading the only device without naming it."""
    backend.api("GET", DEVICES_PATH, json={"devices": [MAC]})
    backend.api("GET", STATUS_PATH, json={"relay": {"state": "on"}})
    backend.api("GET", CONFIG_PATH, json=CONFIG_PAYLOAD)

    info = await client.read_info()

    assert info.mac == MAC
    assert info.relay_state is True
    assert info.windows == CONFIG.windows


@pytest.mark.parametrize(
    ("devices", "message"),
    [([], "No ThermoSave devices"), ([MAC, OTHER_MAC], "More than one device")],
)
async def test_read_info_ambiguous(
    backend: MockBackend,
    client: ThermosaveClient,
    devices: list[str],
    message: str,
) -> None:
    """Test a device must be named unless exactly one is claimed."""
    backend.api("GET", DEVICES_PATH, json={"devices": devices})

    with pytest.raises(ThermosaveApiError, match=message):
        await client.read_info()


@pytest.mark.parametrize(
    ("method", "args", "update"),
    [
        ("set_mode", (" ON ",), {"mode": "on"}),
        ("set_mode", (ThermosaveMode.OFF,), {"mode": "off"}),
        (
            "set_schedule",
            (
                [
                    ScheduleWindow(start="17:00", end="19:00"),
                    {"start": "22:00", "end": "06:00"},
                ],
            ),
            {
                "windows": [
                    {"start": "17:00", "end": "19:00"},
                    {"start": "22:00", "end": "06:00"},
                ]
            },
        ),
        ("set_timezone", (" Europe/Oslo ",), {"timezone": "Europe/Oslo"}),
    ],
)
async def test_update_device_config(
    backend: MockBackend,
    client: ThermosaveClient,
    method: str,
    args: tuple[Any, ...],
    update: dict[str, Any],
) -> None:
    """Test config updates are patched and the new config read back."""
    backend.api("PATCH", CONFIG_PATH, status=HTTPStatus.NO_CONTENT)
    backend.api("GET", CONFIG_PATH, json=CONFIG_PAYLOAD)

    assert await getattr(client, method)(MAC, *args) == CONFIG

    assert backend.api_calls()[0][:2] == ("PATCH", update)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "eco"}, "Unsupported mode 'eco'"),
        ({"windows": [{"start": "17:00"}]}, "needs start and end"),
        ({"windows": [ScheduleWindow(start="25:00", end="19:00")]}, "Invalid HH:MM"),
        ({"timezone": " "}, "timezone must not be empty"),
        ({}, "At least one config field"),
    ],
)
async def test_update_device_config_invalid(
    client: ThermosaveClient, kwargs: dict[str, Any], message: str
) -> None:
    """Test invalid config updates are rejected before any request."""
    with pytest.raises(ValueError, match=message):
        await client.update_device_config(MAC, **kwargs)


async def test_update_device_config_error(
    backend: MockBackend, client: ThermosaveClient
) -> None:
    """Test a rejected config update is raised."""
    backend.api("PATCH", CONFIG_PATH, status=HTTPStatus.BAD_REQUEST, json={})

    with pytest.raises(ThermosaveApiError, match="HTTP 400"):
        await client.set_mode(MAC, "on")


@pytest.mark.parametrize(
    ("method", "kwargs", "mode"),
    [
        ("set_state", {"state": True}, "on"),
        ("set_state", {"state": False}, "off"),
        ("set_auto", {}, "auto"),
    ],
)
async def test_set_state(
    backend: MockBackend,
    client: ThermosaveClient,
    method: str,
    kwargs: dict[str, Any],
    mode: str,
) -> None:
    """Test forcing the relay or returning to automatic control."""
    backend.api("GET", DEVICES_PATH, json={"devices": [MAC]})
    backend.api("PATCH", CONFIG_PATH, json={})
    backend.api("GET", CONFIG_PATH, json={**CONFIG_PAYLOAD, "mode": mode})
    backend.api("GET", STATUS_PATH, json={"mode": mode})
    backend.api("GET", CONFIG_PATH, json={**CONFIG_PAYLOAD, "mode": mode})

    info = await getattr(client, method)(**kwargs)

    assert info.mode_config == mode
    assert info.mode_status == mode
    assert ("PATCH", {"mode": mode}) in [call[:2] for call in backend.api_calls()]


def test_unit_info() -> None:
    """Test the convenience properties of the combined device record."""
    info = UnitInfo.from_parts(MAC, None, None)

    assert info.unit_id == MAC
    assert info.name == f"ThermoSave {MAC}"
    assert info.is_on is None
    assert not info.status_available
    assert not info.config_available
