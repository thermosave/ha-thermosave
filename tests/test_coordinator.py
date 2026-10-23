"""Tests for the ThermoSave data update coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thermosave.const import (
    CONFIG_UPDATE_INTERVAL,
    DEVICES_UPDATE_INTERVAL,
    STATUS_UPDATE_INTERVAL,
)
from custom_components.thermosave.pythermosave import (
    ThermosaveAuthenticationError,
    ThermosaveError,
)

from .conftest import MAC, get_entity_id

if TYPE_CHECKING:
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

# Freeze time before setup so the cache ages are measured on the frozen clock.
pytestmark = pytest.mark.usefixtures("freezer", "init_integration")

OTHER_MAC = "11:22:33:44:55:66"


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _state(hass: HomeAssistant, mac: str = MAC) -> str:
    state = hass.states.get(get_entity_id(hass, SENSOR_DOMAIN, "state", mac))
    assert state is not None
    return state.state


async def test_update_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
) -> None:
    """Test entities become unavailable on errors and recover afterwards."""
    mock_client.get_device_status.side_effect = ThermosaveError("boom")
    await _tick(hass, freezer, STATUS_UPDATE_INTERVAL)
    assert _state(hass) == STATE_UNAVAILABLE

    mock_client.get_device_status.side_effect = None
    await _tick(hass, freezer, STATUS_UPDATE_INTERVAL)
    assert _state(hass) == "heating"


async def test_update_auth_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
) -> None:
    """Test rejected credentials during polling start a reauth flow."""
    mock_client.get_device_status.side_effect = ThermosaveAuthenticationError("no")
    await _tick(hass, freezer, STATUS_UPDATE_INTERVAL)

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_config_cached(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
) -> None:
    """Test the device list and config are only refetched once stale."""
    assert mock_client.list_devices.await_count == 1
    assert mock_client.get_device_config.await_count == 1

    await _tick(hass, freezer, STATUS_UPDATE_INTERVAL)
    assert mock_client.get_device_status.await_count == 2
    assert mock_client.list_devices.await_count == 1
    assert mock_client.get_device_config.await_count == 1

    await _tick(hass, freezer, CONFIG_UPDATE_INTERVAL - STATUS_UPDATE_INTERVAL)
    assert mock_client.list_devices.await_count == 2
    assert mock_client.get_device_config.await_count == 2


async def test_devices_change(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
) -> None:
    """Test removed devices become unavailable and new devices are added."""
    mock_client.list_devices.return_value = (OTHER_MAC,)
    await _tick(hass, freezer, DEVICES_UPDATE_INTERVAL)

    assert _state(hass) == STATE_UNAVAILABLE
    assert _state(hass, OTHER_MAC) == "heating"
    mock_client.get_device_status.assert_awaited_with(OTHER_MAC)
