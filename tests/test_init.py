"""Tests for ThermoSave setup."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState

from custom_components.thermosave.pythermosave import ThermosaveAuthenticationError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


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
