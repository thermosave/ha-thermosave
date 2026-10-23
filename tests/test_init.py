"""Tests for ThermoSave setup."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState

from custom_components.thermosave.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
)
from custom_components.thermosave.pythermosave import (
    ThermosaveAuthenticationError,
    TokenSet,
)

from .conftest import TOKENS, make_config, make_status

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """Test the config entry loads and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_store_refreshed_tokens(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test tokens refreshed by the client are stored in the config entry."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.thermosave.ThermosaveClient",
        autospec=True,
    ) as client_class:
        client: AsyncMock = client_class.return_value
        client.list_devices.return_value = ()
        client.get_device_status.return_value = make_status()
        client.get_device_config.return_value = make_config()
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    store_tokens = client_class.call_args.kwargs["token_update_callback"]
    with patch.object(hass.config_entries, "async_update_entry") as update_entry:
        await store_tokens(
            TokenSet(
                mock_config_entry.data[CONF_ACCESS_TOKEN],
                mock_config_entry.data[CONF_REFRESH_TOKEN],
                mock_config_entry.data[CONF_EXPIRES_AT],
            )
        )
    update_entry.assert_not_called()

    await store_tokens(TOKENS)
    assert mock_config_entry.data[CONF_ACCESS_TOKEN] == TOKENS.access_token
    assert mock_config_entry.data[CONF_REFRESH_TOKEN] == TOKENS.refresh_token
    assert mock_config_entry.data[CONF_EXPIRES_AT] == TOKENS.expires_at


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test rejected credentials during setup start a reauth flow."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.thermosave.ThermosaveClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.list_devices.side_effect = (
            ThermosaveAuthenticationError("Refresh token has been revoked")
        )
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id
