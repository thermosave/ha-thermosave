"""Tests for the ThermoSave schedule calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.thermosave.pythermosave import DeviceConfig, ScheduleWindow

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the API client used by the integration."""
    with patch(
        "custom_components.thermosave.ThermosaveClient",
        autospec=True,
    ) as client_class:
        client = client_class.return_value
        client.list_devices.return_value = (MAC,)
        client.get_device_status.return_value = None
        client.get_device_config.return_value = DeviceConfig(
            timezone="UTC", windows=(), mode="auto", raw={}
        )
        client.set_schedule.return_value = DeviceConfig(
            timezone="UTC",
            windows=(ScheduleWindow(start="17:00", end="19:00"),),
            mode="auto",
            raw={},
        )
        yield client


@pytest.fixture
async def calendar_entity_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> str:
    """Set up the integration and return the schedule calendar entity ID."""
    await hass.config.async_set_time_zone("UTC")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        CALENDAR_DOMAIN, "thermosave", f"{MAC}_schedule"
    )
    assert entity_id is not None
    return entity_id


async def _create_event(hass: HomeAssistant, entity_id: str, **times: object) -> None:
    await hass.services.async_call(
        CALENDAR_DOMAIN,
        "create_event",
        {ATTR_ENTITY_ID: entity_id, "summary": "Power saving", **times},
        blocking=True,
    )


async def test_create_event(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test creating an event appends a schedule window."""
    start = dt_util.now().replace(hour=17, minute=0, second=0, microsecond=0)
    await _create_event(
        hass,
        calendar_entity_id,
        start_date_time=start,
        end_date_time=start + timedelta(hours=2),
    )

    mock_client.set_schedule.assert_awaited_once_with(
        MAC, [ScheduleWindow(start="17:00", end="19:00")]
    )


async def test_create_all_day_event(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test an all-day event is rejected as a validation error."""
    with pytest.raises(ServiceValidationError, match="not all-day dates"):
        await _create_event(
            hass,
            calendar_entity_id,
            start_date=date(2026, 10, 23),
            end_date=date(2026, 10, 24),
        )
    mock_client.set_schedule.assert_not_awaited()


async def test_create_event_longer_than_a_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test a window longer than 24 hours is rejected as a validation error."""
    start = datetime(2026, 10, 23, 17, tzinfo=dt_util.UTC)
    with pytest.raises(ServiceValidationError, match="at most 24 hours"):
        await _create_event(
            hass,
            calendar_entity_id,
            start_date_time=start,
            end_date_time=start + timedelta(hours=25),
        )
    mock_client.set_schedule.assert_not_awaited()
