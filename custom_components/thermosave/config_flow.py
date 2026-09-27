"""Config flow for Thermosave."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.const import CONF_EMAIL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    API_BASE_URL,
    COGNITO_BASE_URL,
    COGNITO_CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .pythermosave import (
    ThermosaveAuthenticationError,
    ThermosaveClient,
    ThermosaveConnectionError,
    ThermosaveError,
    ThermosaveInvalidCodeError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

CONF_CODE = "code"


class ThermosaveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thermosave."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str | None = None
        self._client: ThermosaveClient | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect the email address and request a Cognito email OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().casefold()
            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            self._client = self._new_client()
            try:
                await self._client.request_auth_code(self._email)
            except ThermosaveConnectionError:
                errors["base"] = "cannot_connect"
            except ThermosaveAuthenticationError:
                errors["base"] = "invalid_auth"
            except (ThermosaveError, ValueError):
                errors["base"] = "unknown"
            else:
                return await self.async_step_code()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_code(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Verify the Cognito OTP and store the returned tokens."""
        errors: dict[str, str] = {}

        if self._email is None or self._client is None:
            return self.async_abort(reason="flow_state_missing")

        if user_input is not None:
            try:
                tokens = await self._client.authenticate(
                    self._email,
                    user_input[CONF_CODE].strip(),
                )
            except ThermosaveInvalidCodeError:
                errors["base"] = "invalid_code"
            except ThermosaveConnectionError:
                errors["base"] = "cannot_connect"
            except ThermosaveAuthenticationError:
                errors["base"] = "invalid_auth"
            except ThermosaveError:
                errors["base"] = "unknown"
            else:
                entry_data = {
                    CONF_EMAIL: self._email,
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_EXPIRES_AT: tokens.expires_at,
                }

                if self.source == SOURCE_REAUTH:
                    reauth_entry = self._get_reauth_entry()
                    await self.async_set_unique_id(self._email)
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data=entry_data,
                    )

                return self.async_create_entry(
                    title=self._email,
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Start reauthentication when Cognito rejects the refresh token."""
        self._email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask the user to request a fresh Cognito email OTP."""
        errors: dict[str, str] = {}
        if self._email is None:
            return self.async_abort(reason="flow_state_missing")

        if user_input is not None:
            self._client = self._new_client()
            try:
                await self._client.request_auth_code(self._email)
            except ThermosaveConnectionError:
                errors["base"] = "cannot_connect"
            except ThermosaveAuthenticationError:
                errors["base"] = "invalid_auth"
            except ThermosaveError:
                errors["base"] = "unknown"
            else:
                return await self.async_step_code()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    def _new_client(self) -> ThermosaveClient:
        """Create an unauthenticated API client for the config flow."""
        return ThermosaveClient(
            async_get_clientsession(self.hass),
            cognito_client_id=COGNITO_CLIENT_ID,
            cognito_base_url=COGNITO_BASE_URL,
            api_base_url=API_BASE_URL,
        )
