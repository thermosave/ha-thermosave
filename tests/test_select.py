"""Tests for the ThermoSave mode select."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError

from custom_components.thermosave.pythermosave import ThermosaveError

from .conftest import MAC, get_entity_id, make_config, setup_integration

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _select_option(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: get_entity_id(hass, SELECT_DOMAIN, "mode"),
            ATTR_OPTION: option,
        },
        blocking=True,
    )


@pytest.mark.usefixtures("init_integration")
async def test_select_option(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Test selecting a mode writes it and shows the returned config."""
    entity_id = get_entity_id(hass, SELECT_DOMAIN, "mode")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "auto"

    await _select_option(hass, "on")
    await hass.async_block_till_done()

    mock_client.set_mode.assert_awaited_once_with(MAC, "on")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


@pytest.mark.usefixtures("init_integration")
async def test_select_option_error(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """Test a failed mode write is raised as a Home Assistant error."""
    mock_client.set_mode.side_effect = ThermosaveError("boom")

    with pytest.raises(HomeAssistantError, match="Unable to set ThermoSave mode"):
        await _select_option(hass, "off")


async def test_unknown_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the select is unavailable for a mode it does not know."""
    mock_client.get_device_config.return_value = make_config(mode="eco")
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(get_entity_id(hass, SELECT_DOMAIN, "mode"))
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
