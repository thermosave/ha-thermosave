"""Tests for the ThermoSave water heater."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.water_heater import (
    ATTR_OPERATION_LIST,
    ATTR_OPERATION_MODE,
    SERVICE_SET_OPERATION_MODE,
    STATE_ECO,
    STATE_PERFORMANCE,
)
from homeassistant.components.water_heater import (
    DOMAIN as WATER_HEATER_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
)
from homeassistant.exceptions import HomeAssistantError

from custom_components.thermosave.pythermosave import ThermosaveError

from .conftest import MAC, get_entity_id, make_config, setup_integration

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _call(hass: HomeAssistant, service: str, **data: object) -> None:
    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        service,
        {ATTR_ENTITY_ID: get_entity_id(hass, WATER_HEATER_DOMAIN, "water_heater")}
        | data,
        blocking=True,
    )
    await hass.async_block_till_done()


def _state(hass: HomeAssistant) -> str:
    state = hass.states.get(get_entity_id(hass, WATER_HEATER_DOMAIN, "water_heater"))
    assert state is not None
    return state.state


@pytest.mark.usefixtures("init_integration")
async def test_water_heater(hass: HomeAssistant) -> None:
    """Test the water heater shows the configured mode."""
    state = hass.states.get(get_entity_id(hass, WATER_HEATER_DOMAIN, "water_heater"))
    assert state is not None
    assert state.state == STATE_ECO
    assert state.attributes[ATTR_OPERATION_MODE] == STATE_ECO
    assert state.attributes[ATTR_OPERATION_LIST] == [
        STATE_ECO,
        STATE_PERFORMANCE,
        STATE_OFF,
    ]


@pytest.mark.parametrize(
    ("operation", "mode"),
    [(STATE_ECO, "auto"), (STATE_PERFORMANCE, "on"), (STATE_OFF, "off")],
)
@pytest.mark.usefixtures("init_integration")
async def test_set_operation_mode(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    operation: str,
    mode: str,
) -> None:
    """Test setting an operation mode writes the matching device mode."""
    mock_client.set_mode.return_value = make_config(mode=mode)

    await _call(hass, SERVICE_SET_OPERATION_MODE, operation_mode=operation)

    mock_client.set_mode.assert_awaited_once_with(MAC, mode)
    assert _state(hass) == operation


@pytest.mark.parametrize(
    ("service", "mode", "expected"),
    [(SERVICE_TURN_ON, "auto", STATE_ECO), (SERVICE_TURN_OFF, "off", STATE_OFF)],
)
@pytest.mark.usefixtures("init_integration")
async def test_turn_on_off(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    service: str,
    mode: str,
    expected: str,
) -> None:
    """Test turning on follows the schedule and turning off forces the device off."""
    mock_client.set_mode.return_value = make_config(mode=mode)

    await _call(hass, service)

    mock_client.set_mode.assert_awaited_once_with(MAC, mode)
    assert _state(hass) == expected


@pytest.mark.usefixtures("init_integration")
async def test_set_operation_mode_error(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Test a failed mode write is raised as a Home Assistant error."""
    mock_client.set_mode.side_effect = ThermosaveError("boom")

    with pytest.raises(HomeAssistantError, match="Unable to set ThermoSave mode"):
        await _call(hass, SERVICE_SET_OPERATION_MODE, operation_mode=STATE_OFF)


async def test_unknown_mode(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the water heater is unavailable for a mode it does not know."""
    mock_client.get_device_config.return_value = make_config(mode="eco")
    await setup_integration(hass, mock_config_entry)

    assert _state(hass) == STATE_UNAVAILABLE
