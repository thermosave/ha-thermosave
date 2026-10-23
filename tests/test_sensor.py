"""Tests for ThermoSave sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import STATE_UNAVAILABLE

from .conftest import get_entity_id, make_status, setup_integration

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def _state(hass: HomeAssistant, key: str) -> str:
    state = hass.states.get(get_entity_id(hass, SENSOR_DOMAIN, key))
    assert state is not None
    return state.state


@pytest.mark.usefixtures("init_integration")
async def test_sensors(hass: HomeAssistant) -> None:
    """Test the sensor values of an online device."""
    assert _state(hass, "state") == "heating"
    assert _state(hass, "power") == "2.5"
    assert _state(hass, "last_seen") == "2026-10-23T12:00:00+00:00"
    assert _state(hass, "timezone") == "UTC"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"connection_state": "offline"}, "offline"),
        ({"connection_state": None}, "offline"),
        ({"mode": "off"}, "away"),
        ({"relay_state": False}, "paused"),
        ({"relay_state": False, "mode": "on"}, "ready"),
        ({"power_kw": 0.05}, "ready"),
        ({"power_kw": None}, "ready"),
    ],
)
async def test_state_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    changes: dict[str, object],
    expected: str,
) -> None:
    """Test the operational state mirrors the ThermoSave app."""
    mock_client.get_device_status.return_value = make_status(**changes)
    await setup_integration(hass, mock_config_entry)

    assert _state(hass, "state") == expected


async def test_sensors_without_status(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test status sensors are unavailable when no status is reported."""
    mock_client.get_device_status.return_value = None
    await setup_integration(hass, mock_config_entry)

    assert _state(hass, "state") == STATE_UNAVAILABLE
    assert _state(hass, "power") == STATE_UNAVAILABLE
    assert _state(hass, "last_seen") == STATE_UNAVAILABLE
    assert _state(hass, "timezone") == "UTC"


async def test_sensors_without_values(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test sensors are unavailable when their value is missing."""
    mock_client.get_device_status.return_value = make_status(
        power_kw=None, last_seen=None
    )
    mock_client.get_device_config.return_value = None
    await setup_integration(hass, mock_config_entry)

    assert _state(hass, "state") == "ready"
    assert _state(hass, "power") == STATE_UNAVAILABLE
    assert _state(hass, "last_seen") == STATE_UNAVAILABLE
    assert _state(hass, "timezone") == STATE_UNAVAILABLE
