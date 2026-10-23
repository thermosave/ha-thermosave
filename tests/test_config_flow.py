"""Tests for the ThermoSave config flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL
from homeassistant.data_entry_flow import FlowResultType

from custom_components.thermosave.config_flow import CONF_CODE
from custom_components.thermosave.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.thermosave.pythermosave import (
    ThermosaveAuthenticationError,
    ThermosaveConnectionError,
    ThermosaveError,
    ThermosaveInvalidCodeError,
)

from .conftest import EMAIL, TOKENS

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

EXPECTED_DATA = {
    CONF_EMAIL: EMAIL,
    CONF_ACCESS_TOKEN: TOKENS.access_token,
    CONF_REFRESH_TOKEN: TOKENS.refresh_token,
    CONF_EXPIRES_AT: TOKENS.expires_at,
}


async def test_user_flow(hass: HomeAssistant, mock_flow_client: AsyncMock) -> None:
    """Test a full user flow, including email normalization."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: " User@Example.com "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    mock_flow_client.request_auth_code.assert_awaited_once_with(EMAIL)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: " 123456 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == EXPECTED_DATA
    assert result["result"].unique_id == EMAIL
    mock_flow_client.authenticate.assert_awaited_once_with(EMAIL, "123456")


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThermosaveConnectionError, "cannot_connect"),
        (ThermosaveAuthenticationError, "invalid_auth"),
        (ThermosaveError, "unknown"),
        (ValueError, "unknown"),
    ],
)
async def test_user_flow_request_code_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Test errors when requesting a code, then recovering."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    mock_flow_client.request_auth_code.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_flow_client.request_auth_code.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThermosaveInvalidCodeError, "invalid_code"),
        (ThermosaveConnectionError, "cannot_connect"),
        (ThermosaveAuthenticationError, "invalid_auth"),
        (ThermosaveError, "unknown"),
    ],
)
async def test_user_flow_code_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Test errors when verifying the code, then recovering."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL}
    )
    mock_flow_client.authenticate.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "000000"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    assert result["errors"] == {"base": error}

    mock_flow_client.authenticate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that an account can only be configured once."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL.upper()}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_flow_client.request_auth_code.assert_not_awaited()


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reauthentication replaces the stored tokens."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["email"] == EMAIL

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    mock_flow_client.request_auth_code.assert_awaited_once_with(EMAIL)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert dict(mock_config_entry.data) == EXPECTED_DATA
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThermosaveConnectionError, "cannot_connect"),
        (ThermosaveAuthenticationError, "invalid_auth"),
        (ThermosaveError, "unknown"),
    ],
)
async def test_reauth_flow_request_code_errors(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Test errors when requesting a reauth code, then recovering."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    mock_flow_client.request_auth_code.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": error}

    mock_flow_client.request_auth_code.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert dict(mock_config_entry.data) == EXPECTED_DATA


async def test_reauth_flow_code_error(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test an invalid code during reauth, then recovering."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    mock_flow_client.authenticate.side_effect = ThermosaveInvalidCodeError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "000000"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    assert result["errors"] == {"base": "invalid_code"}

    mock_flow_client.authenticate.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert dict(mock_config_entry.data) == EXPECTED_DATA


async def test_reauth_flow_wrong_account(
    hass: HomeAssistant,
    mock_flow_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reauth aborts when the email does not match the entry."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, unique_id="other@example.com"
    )

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data[CONF_ACCESS_TOKEN] == "old-access"
