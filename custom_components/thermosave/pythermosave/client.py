"""Async client for ThermoSave Cognito authentication and cloud API."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import aiohttp

from .exceptions import (
    ThermosaveApiError,
    ThermosaveAuthenticationError,
    ThermosaveConnectionError,
    ThermosaveInvalidCodeError,
)
from .models import (
    AuthSession,
    DeviceConfig,
    DeviceStatus,
    ScheduleWindow,
    ThermosaveMode,
    TokenSet,
    UnitInfo,
)

DEFAULT_COGNITO_BASE_URL = "https://cognito-idp.us-west-1.amazonaws.com"
DEFAULT_API_BASE_URL = "https://api.thermosave.com"
_COGNITO_TARGET_PREFIX = "AWSCognitoIdentityProviderService"
_MAC_PATTERN = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")

TokenUpdateCallback = Callable[[TokenSet], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class ThermosaveEndpoints:
    """ThermoSave backend endpoint templates."""

    claim_device: str = "/v1/devices/claim"
    devices: str = "/v1/devices"
    device_status: str = "/v1/devices/{mac}/status"
    device_config: str = "/v1/devices/{mac}/config"


class ThermosaveClient:
    """Client for ThermoSave authentication and device communication."""

    def __init__(  # noqa: PLR0913
        self,
        session: aiohttp.ClientSession,
        *,
        cognito_client_id: str,
        cognito_base_url: str = DEFAULT_COGNITO_BASE_URL,
        api_base_url: str = DEFAULT_API_BASE_URL,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float | None = None,
        token_update_callback: TokenUpdateCallback | None = None,
        endpoints: ThermosaveEndpoints | None = None,
        request_timeout: float = 15.0,
    ) -> None:
        """Initialize the client; pass stored tokens to resume a session."""
        if not cognito_client_id.strip():
            raise ValueError("cognito_client_id must not be empty")

        self._session = session
        self._cognito_client_id = cognito_client_id.strip()
        self._cognito_base_url = cognito_base_url.rstrip("/")
        self._api_base_url = api_base_url.rstrip("/")
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._token_update_callback = token_update_callback
        self._endpoints = endpoints or ThermosaveEndpoints()
        self._request_timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._refresh_lock = asyncio.Lock()
        self._pending_auth: AuthSession | None = None

    @property
    def tokens(self) -> TokenSet | None:
        """Return the current token set, if authenticated."""
        if self._access_token is None or self._refresh_token is None:
            return None
        return TokenSet(
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            expires_at=self._expires_at,
        )

    @property
    def pending_auth(self) -> AuthSession | None:
        """Return the pending Cognito OTP session, if any."""
        return self._pending_auth

    async def request_auth_code(self, email: str) -> AuthSession:
        """Sign up if needed, then request a passwordless email OTP."""
        normalized_email = self._normalize_email(email)

        try:
            await self._cognito_request(
                "SignUp",
                {
                    "ClientId": self._cognito_client_id,
                    "Username": normalized_email,
                    "UserAttributes": [{"Name": "email", "Value": normalized_email}],
                },
            )
        except ThermosaveApiError as err:
            if err.code != "UsernameExistsException":
                raise

        payload = await self._cognito_request(
            "InitiateAuth",
            {
                "AuthFlow": "USER_AUTH",
                "ClientId": self._cognito_client_id,
                "AuthParameters": {
                    "USERNAME": normalized_email,
                    "PREFERRED_CHALLENGE": "EMAIL_OTP",
                },
            },
        )

        session = payload.get("Session")
        if not isinstance(session, str) or not session:
            raise ThermosaveAuthenticationError(
                "Cognito did not return an email OTP session"
            )

        challenge_name = payload.get("ChallengeName")
        if challenge_name not in (None, "EMAIL_OTP"):
            raise ThermosaveAuthenticationError(
                f"Cognito returned unsupported challenge {challenge_name!r}"
            )

        self._pending_auth = AuthSession(normalized_email, session)
        return self._pending_auth

    async def authenticate(
        self,
        email: str,
        code: str,
        *,
        session: str | None = None,
    ) -> TokenSet:
        """Respond to the Cognito EMAIL_OTP challenge."""
        normalized_email = self._normalize_email(email)
        challenge_session = session
        if (
            challenge_session is None
            and self._pending_auth is not None
            and self._pending_auth.email == normalized_email
        ):
            challenge_session = self._pending_auth.session

        if not challenge_session:
            raise ThermosaveAuthenticationError(
                "No pending email OTP session; request a new code first"
            )

        try:
            payload = await self._cognito_request(
                "RespondToAuthChallenge",
                {
                    "ChallengeName": "EMAIL_OTP",
                    "ClientId": self._cognito_client_id,
                    "Session": challenge_session,
                    "ChallengeResponses": {
                        "USERNAME": normalized_email,
                        "EMAIL_OTP_CODE": code.strip(),
                    },
                },
            )
        except ThermosaveApiError as err:
            if err.code in {
                "CodeMismatchException",
                "ExpiredCodeException",
                "NotAuthorizedException",
            }:
                raise ThermosaveInvalidCodeError(str(err)) from err
            raise

        tokens = self._parse_authentication_result(
            payload,
            require_refresh_token=True,
        )
        self._pending_auth = None
        await self._set_tokens(tokens)
        return tokens

    async def refresh_access_token(self) -> TokenSet:
        """Force a Cognito refresh and return the current token set."""
        await self._refresh_access_token(expected_access_token=None, force=True)
        tokens = self.tokens
        if tokens is None:
            raise ThermosaveAuthenticationError("Token refresh returned no tokens")
        return tokens

    async def claim_device(self, mac: str, nonce: str, signature: str) -> None:
        """Claim a device for the authenticated account."""
        normalized_mac = self._normalize_mac(mac)
        status, payload = await self._api_request(
            "POST",
            self._endpoints.claim_device,
            json_payload={
                "mac": normalized_mac,
                "nonce": nonce,
                "signature": signature,
            },
        )
        if status not in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
            self._raise_api_error(status, payload)

    async def list_devices(self) -> tuple[str, ...]:
        """Return lowercase MAC addresses claimed by the account."""
        status, payload = await self._api_request("GET", self._endpoints.devices)
        if status != HTTPStatus.OK:
            self._raise_api_error(status, payload)

        devices = payload.get("devices")
        if not isinstance(devices, Sequence) or isinstance(devices, (str, bytes)):
            raise ThermosaveApiError("Device list response did not contain devices")

        normalized = [
            self._normalize_mac(device) for device in devices if isinstance(device, str)
        ]
        return tuple(dict.fromkeys(normalized))

    async def get_device_status(self, mac: str) -> DeviceStatus | None:
        """Return status for a device, or None for any non-200 response."""
        normalized_mac = self._normalize_mac(mac)
        path = self._device_path(self._endpoints.device_status, normalized_mac)
        status, payload = await self._api_request("GET", path)
        if status != HTTPStatus.OK:
            return None
        return self._parse_device_status(normalized_mac, payload)

    async def get_device_config(self, mac: str) -> DeviceConfig | None:
        """
        Return device config, or None when the device has none yet.

        The backend answers 204 when the device has no shadow, and 404 when the
        shadow lacks windows or a timezone.
        """
        normalized_mac = self._normalize_mac(mac)
        path = self._device_path(self._endpoints.device_config, normalized_mac)
        status, payload = await self._api_request("GET", path)
        if status in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND):
            return None
        if status != HTTPStatus.OK:
            self._raise_api_error(status, payload)
        return self._parse_device_config(payload)

    async def read_info(self, mac: str | None = None) -> UnitInfo:
        """Read combined status and configuration for one device."""
        normalized_mac = await self._resolve_mac(mac)
        status, config = await asyncio.gather(
            self.get_device_status(normalized_mac),
            self.get_device_config(normalized_mac),
        )

        return UnitInfo(
            mac=normalized_mac,
            connection_state=status.connection_state if status else None,
            last_seen=status.last_seen if status else None,
            power_kw=status.power_kw if status else None,
            mode_status=status.mode if status else None,
            mode_config=config.mode if config else None,
            relay_state=status.relay_state if status else None,
            timezone=config.timezone if config else None,
            windows=config.windows if config else (),
            status_available=status is not None,
            config_available=config is not None,
            status_raw=status.raw if status else None,
            config_raw=config.raw if config else None,
        )

    async def update_device_config(
        self,
        mac: str,
        *,
        mode: str | None = None,
        windows: Sequence[ScheduleWindow | Mapping[str, str]] | None = None,
        timezone: str | None = None,
    ) -> DeviceConfig | None:
        """Apply a partial update to device configuration."""
        normalized_mac = self._normalize_mac(mac)
        update: dict[str, Any] = {}

        if mode is not None:
            try:
                normalized_mode = ThermosaveMode(str(mode).strip().lower()).value
            except ValueError as err:
                allowed = ", ".join(mode.value for mode in ThermosaveMode)
                raise ValueError(
                    f"Unsupported mode {mode!r}; expected one of: {allowed}"
                ) from err
            update["mode"] = normalized_mode

        if windows is not None:
            update["windows"] = [self._serialize_window(window) for window in windows]

        if timezone is not None:
            stripped_timezone = timezone.strip()
            if not stripped_timezone:
                raise ValueError("timezone must not be empty")
            update["timezone"] = stripped_timezone

        if not update:
            raise ValueError("At least one config field must be supplied")

        path = self._device_path(self._endpoints.device_config, normalized_mac)
        status, payload = await self._api_request(
            "PATCH",
            path,
            json_payload=update,
        )
        if status not in (HTTPStatus.OK, HTTPStatus.NO_CONTENT):
            self._raise_api_error(status, payload)

        return await self.get_device_config(normalized_mac)

    async def set_mode(
        self,
        mac: str,
        mode: str | ThermosaveMode,
    ) -> DeviceConfig | None:
        """Set the mode to ``auto``, ``on``, or ``off``."""
        return await self.update_device_config(mac, mode=str(mode))

    async def set_schedule(
        self,
        mac: str,
        windows: Sequence[ScheduleWindow | Mapping[str, str]],
    ) -> DeviceConfig | None:
        """Replace the device schedule windows."""
        return await self.update_device_config(mac, windows=windows)

    async def set_timezone(self, mac: str, timezone: str) -> DeviceConfig | None:
        """Set the device timezone."""
        return await self.update_device_config(mac, timezone=timezone)

    async def set_state(self, state: bool, mac: str | None = None) -> UnitInfo:  # noqa: FBT001
        """Force the relay on or off through the documented mode setting."""
        normalized_mac = await self._resolve_mac(mac)
        mode = ThermosaveMode.ON if state else ThermosaveMode.OFF
        await self.set_mode(normalized_mac, mode)
        return await self.read_info(normalized_mac)

    async def set_auto(self, mac: str | None = None) -> UnitInfo:
        """Return the device to automatic schedule control."""
        normalized_mac = await self._resolve_mac(mac)
        await self.set_mode(normalized_mac, ThermosaveMode.AUTO)
        return await self.read_info(normalized_mac)

    async def _resolve_mac(self, mac: str | None) -> str:
        if mac is not None:
            return self._normalize_mac(mac)

        devices = await self.list_devices()
        if not devices:
            raise ThermosaveApiError("No ThermoSave devices are claimed")
        if len(devices) > 1:
            raise ThermosaveApiError(
                "More than one device is claimed; supply a MAC address"
            )
        return devices[0]

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        await self._ensure_valid_access_token()
        failed_access_token = self._access_token

        status, payload = await self._request_once(
            method,
            f"{self._api_base_url}{path}",
            json_payload=json_payload,
            headers=self._api_headers(),
        )

        if status == HTTPStatus.UNAUTHORIZED:
            await self._refresh_access_token(
                expected_access_token=failed_access_token,
                force=True,
            )
            status, payload = await self._request_once(
                method,
                f"{self._api_base_url}{path}",
                json_payload=json_payload,
                headers=self._api_headers(),
            )

        return status, payload

    async def _cognito_request(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        status, response = await self._request_once(
            "POST",
            f"{self._cognito_base_url}/",
            json_payload=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"{_COGNITO_TARGET_PREFIX}.{action}",
            },
        )
        if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
            return response

        code = self._aws_error_code(response)
        message = self._error_message(response, status)
        if action == "InitiateAuth" and code == "NotAuthorizedException":
            raise ThermosaveAuthenticationError(message)
        raise ThermosaveApiError(message, status=status, code=code)

    async def _request_once(
        self,
        method: str,
        url: str,
        *,
        json_payload: Mapping[str, Any] | None,
        headers: Mapping[str, str],
    ) -> tuple[int, Mapping[str, Any]]:
        try:
            async with self._session.request(
                method,
                url,
                json=json_payload,
                headers=headers,
                timeout=self._request_timeout,
            ) as response:
                if response.status == HTTPStatus.NO_CONTENT:
                    return response.status, {}

                try:
                    parsed = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    text = await response.text()
                    parsed = {"message": text} if text else {}

                if not isinstance(parsed, Mapping):
                    parsed = {"data": parsed}
                return response.status, parsed
        except (TimeoutError, aiohttp.ClientError) as err:
            raise ThermosaveConnectionError(
                f"Unable to communicate with ThermoSave: {err}"
            ) from err

    async def _ensure_valid_access_token(self) -> None:
        if self._access_token is None:
            raise ThermosaveAuthenticationError("No access token is available")
        if self._expires_at is None:
            return
        if time.time() >= self._expires_at - 30:
            await self._refresh_access_token(
                expected_access_token=self._access_token,
                force=False,
            )

    async def _refresh_access_token(
        self,
        *,
        expected_access_token: str | None,
        force: bool,
    ) -> None:
        async with self._refresh_lock:
            if (
                expected_access_token is not None
                and self._access_token != expected_access_token
            ):
                return
            if (
                not force
                and self._expires_at is not None
                and time.time() < self._expires_at - 30
            ):
                return
            if self._refresh_token is None:
                raise ThermosaveAuthenticationError("No refresh token is available")

            try:
                payload = await self._cognito_request(
                    "InitiateAuth",
                    {
                        "AuthFlow": "REFRESH_TOKEN_AUTH",
                        "ClientId": self._cognito_client_id,
                        "AuthParameters": {"REFRESH_TOKEN": self._refresh_token},
                    },
                )
            except ThermosaveApiError as err:
                if err.code in {
                    "NotAuthorizedException",
                    "UserNotFoundException",
                    "InvalidParameterException",
                }:
                    raise ThermosaveAuthenticationError(str(err)) from err
                raise

            tokens = self._parse_authentication_result(
                payload,
                require_refresh_token=False,
                fallback_refresh_token=self._refresh_token,
            )
            await self._set_tokens(tokens)

    async def _set_tokens(self, tokens: TokenSet) -> None:
        self._access_token = tokens.access_token
        self._refresh_token = tokens.refresh_token
        self._expires_at = tokens.expires_at

        if self._token_update_callback is None:
            return
        result = self._token_update_callback(tokens)
        if inspect.isawaitable(result):
            await result

    def _api_headers(self) -> dict[str, str]:
        if self._access_token is None:
            raise ThermosaveAuthenticationError("No access token is available")
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

    @staticmethod
    def _parse_authentication_result(
        payload: Mapping[str, Any],
        *,
        require_refresh_token: bool,
        fallback_refresh_token: str | None = None,
    ) -> TokenSet:
        result = payload.get("AuthenticationResult")
        if not isinstance(result, Mapping):
            raise ThermosaveAuthenticationError(
                "Cognito response did not contain AuthenticationResult"
            )

        access_token = result.get("AccessToken")
        refresh_value = result.get("RefreshToken")
        refresh_token = (
            refresh_value
            if isinstance(refresh_value, str) and refresh_value
            else fallback_refresh_token
        )

        if not isinstance(access_token, str) or not access_token:
            raise ThermosaveAuthenticationError(
                "Cognito response did not contain AccessToken"
            )
        if require_refresh_token and not refresh_token:
            raise ThermosaveAuthenticationError(
                "Cognito response did not contain RefreshToken"
            )
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ThermosaveAuthenticationError("No refresh token is available")

        expires_at = ThermosaveClient._parse_expiry(result, access_token)
        return TokenSet(access_token, refresh_token, expires_at)

    @staticmethod
    def _parse_expiry(
        result: Mapping[str, Any],
        access_token: str,
    ) -> float | None:
        expires_in = result.get("ExpiresIn")
        if isinstance(expires_in, (int, float)):
            return time.time() + float(expires_in)
        if isinstance(expires_in, str):
            try:
                return time.time() + float(expires_in)
            except ValueError:
                pass

        # Cognito access tokens are JWTs. Reading exp without signature
        # verification is safe here because it is used only to schedule refresh;
        # the ThermoSave backend still verifies the token itself.
        try:
            encoded_payload = access_token.split(".")[1]
            encoded_payload += "=" * (-len(encoded_payload) % 4)
            jwt_payload = json.loads(
                base64.urlsafe_b64decode(encoded_payload).decode("utf-8")
            )
            exp = jwt_payload.get("exp")
            return float(exp) if isinstance(exp, (int, float)) else None
        except (IndexError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_device_status(mac: str, payload: Mapping[str, Any]) -> DeviceStatus:
        connection = payload.get("connection")
        connection_payload = connection if isinstance(connection, Mapping) else {}
        power = payload.get("power")
        power_payload = power if isinstance(power, Mapping) else {}
        relay = payload.get("relay")
        relay_payload = relay if isinstance(relay, Mapping) else {}

        response_mac = payload.get("id")
        if isinstance(response_mac, str):
            response_mac = ThermosaveClient._normalize_mac(response_mac)
        else:
            response_mac = mac

        return DeviceStatus(
            mac=response_mac,
            connection_state=ThermosaveClient._optional_string(
                connection_payload.get("state")
            ),
            last_seen=ThermosaveClient._parse_datetime(
                connection_payload.get("lastSeen")
            ),
            power_kw=ThermosaveClient._optional_float(power_payload.get("kW")),
            mode=ThermosaveClient._optional_string(payload.get("mode")),
            relay_state=ThermosaveClient._parse_relay_state(relay_payload.get("state")),
            raw=dict(payload),
        )

    @staticmethod
    def _parse_device_config(payload: Mapping[str, Any]) -> DeviceConfig:
        windows_raw = payload.get("windows")
        windows: list[ScheduleWindow] = []
        if isinstance(windows_raw, Sequence) and not isinstance(
            windows_raw, (str, bytes)
        ):
            for raw_window in windows_raw:
                if not isinstance(raw_window, Mapping):
                    continue
                start = raw_window.get("start")
                end = raw_window.get("end")
                if isinstance(start, str) and isinstance(end, str):
                    windows.append(ScheduleWindow(start=start, end=end))

        return DeviceConfig(
            timezone=ThermosaveClient._optional_string(payload.get("timezone")),
            windows=tuple(windows),
            mode=ThermosaveClient._optional_string(payload.get("mode")),
            raw=dict(payload),
        )

    @staticmethod
    def _serialize_window(
        window: ScheduleWindow | Mapping[str, str],
    ) -> dict[str, str]:
        if isinstance(window, ScheduleWindow):
            start, end = window.start, window.end
        else:
            start, end = window.get("start"), window.get("end")

        if not isinstance(start, str) or not isinstance(end, str):
            # ValueError, not TypeError: callers treat all bad windows alike.
            raise ValueError(  # noqa: TRY004
                "Each schedule window needs start and end strings"
            )
        ThermosaveClient._validate_time(start)
        ThermosaveClient._validate_time(end)
        return {"start": start, "end": end}

    @staticmethod
    def _validate_time(value: str) -> None:
        try:
            time.strptime(value, "%H:%M")
        except ValueError as err:
            raise ValueError(f"Invalid HH:MM time: {value}") from err

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_relay_state(value: Any) -> bool | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if normalized == "on":
            return True
        if normalized == "off":
            return False
        return None

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().casefold()
        if not normalized or "@" not in normalized:
            raise ValueError("A valid email address is required")
        return normalized

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        normalized = mac.strip().lower().replace("-", ":")
        if not _MAC_PATTERN.fullmatch(normalized):
            raise ValueError(f"Invalid MAC address: {mac}")
        return normalized

    @staticmethod
    def _device_path(template: str, mac: str) -> str:
        return template.format(mac=quote(mac, safe=""))

    @staticmethod
    def _aws_error_code(payload: Mapping[str, Any]) -> str | None:
        raw_code = payload.get("__type") or payload.get("code")
        if not isinstance(raw_code, str):
            return None
        return raw_code.rsplit("#", 1)[-1].rsplit(".", 1)[-1]

    @staticmethod
    def _error_message(payload: Mapping[str, Any], status: int) -> str:
        for key in ("message", "Message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return f"ThermoSave request failed with HTTP {status}"

    @staticmethod
    def _raise_api_error(status: int, payload: Mapping[str, Any]) -> None:
        message = ThermosaveClient._error_message(payload, status)
        if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise ThermosaveAuthenticationError(message)
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ThermosaveConnectionError(message)
        raise ThermosaveApiError(message, status=status)
