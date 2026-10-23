"""Tests for ThermoSave binary sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE

from .conftest import get_entity_id, make_status, setup_integration

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (make_status(), STATE_ON),
        (make_status(connection_state="offline"), STATE_OFF),
        (None, STATE_UNAVAILABLE),
    ],
)
async def test_online(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    status: object,
    expected: str,
) -> None:
    """Test the online sensor follows the reported connection state."""
    mock_client.get_device_status.return_value = status
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get(get_entity_id(hass, BINARY_SENSOR_DOMAIN, "online"))
    assert state is not None
    assert state.state == expected
