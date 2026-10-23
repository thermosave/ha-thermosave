"""Tests for the ThermoSave schedule calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.components.calendar.const import DATA_COMPONENT
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.thermosave.pythermosave import ScheduleWindow, ThermosaveError

from .conftest import MAC, get_entity_id, make_config, setup_integration

if TYPE_CHECKING:
    from unittest.mock import AsyncMock

    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator

EVENING = ScheduleWindow(start="17:00", end="19:00")
NIGHT = ScheduleWindow(start="22:00", end="06:00")


@pytest.fixture
async def calendar_entity_id(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> str:
    """Set up the integration and return the schedule calendar entity ID."""
    return get_entity_id(hass, CALENDAR_DOMAIN, "schedule")


async def _setup_with_windows(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    *windows: ScheduleWindow,
    timezone: str = "UTC",
) -> str:
    mock_client.get_device_config.return_value = make_config(
        windows=windows, timezone=timezone
    )
    await setup_integration(hass, mock_config_entry)
    return get_entity_id(hass, CALENDAR_DOMAIN, "schedule")


async def _create_event(hass: HomeAssistant, entity_id: str, **times: object) -> None:
    await hass.services.async_call(
        CALENDAR_DOMAIN,
        "create_event",
        {ATTR_ENTITY_ID: entity_id, "summary": "Power saving", **times},
        blocking=True,
    )


def _uid(index: int) -> str:
    return f"thermosave:{MAC}:window:{index}"


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


async def test_create_event_exactly_a_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test a 24 hour window, which starts and ends at the same time, is rejected."""
    start = datetime(2026, 10, 23, 17, tzinfo=dt_util.UTC)
    with pytest.raises(ServiceValidationError, match="zero time window"):
        await _create_event(
            hass,
            calendar_entity_id,
            start_date_time=start,
            end_date_time=start + timedelta(days=1),
        )
    mock_client.set_schedule.assert_not_awaited()


async def test_create_event_without_timezone(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test a naive event passed straight to the entity is rejected."""
    entity = hass.data[DATA_COMPONENT].get_entity(calendar_entity_id)
    start = datetime(2026, 10, 23, 17)  # noqa: DTZ001
    with pytest.raises(ServiceValidationError, match="must include a timezone"):
        await entity.async_create_event(dtstart=start, dtend=start + timedelta(hours=2))
    mock_client.set_schedule.assert_not_awaited()


async def test_create_event_api_error(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    calendar_entity_id: str,
) -> None:
    """Test a failed schedule write is raised as a Home Assistant error."""
    mock_client.set_schedule.side_effect = ThermosaveError("boom")
    start = datetime(2026, 10, 23, 17, tzinfo=dt_util.UTC)
    with pytest.raises(HomeAssistantError, match="Unable to update the ThermoSave"):
        await _create_event(
            hass,
            calendar_entity_id,
            start_date_time=start,
            end_date_time=start + timedelta(hours=2),
        )


async def test_create_event_device_timezone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test event times are converted to the device timezone."""
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, timezone="America/New_York"
    )
    start = datetime(2026, 10, 23, 17, tzinfo=dt_util.UTC)
    await _create_event(
        hass, entity_id, start_date_time=start, end_date_time=start + timedelta(hours=2)
    )

    mock_client.set_schedule.assert_awaited_once_with(
        MAC, [ScheduleWindow(start="13:00", end="15:00")]
    )


async def test_create_event_invalid_device_timezone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test an unknown device timezone falls back to the Home Assistant one."""
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, timezone="Not/A_Zone"
    )
    await hass.config.async_set_time_zone("Europe/Oslo")
    start = datetime(2026, 10, 23, 17, tzinfo=dt_util.UTC)
    await _create_event(
        hass, entity_id, start_date_time=start, end_date_time=start + timedelta(hours=2)
    )

    mock_client.set_schedule.assert_awaited_once_with(
        MAC, [ScheduleWindow(start="19:00", end="21:00")]
    )


async def test_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test the calendar is on during a window and lists the windows."""
    freezer.move_to("2026-10-23T18:00:00+00:00")
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, EVENING, NIGHT
    )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["message"] == "ThermoSave power saving"
    assert state.attributes["start_time"] == "2026-10-23 17:00:00"
    assert state.attributes["end_time"] == "2026-10-23 19:00:00"
    assert state.attributes["schedule_window_count"] == 2
    assert state.attributes["windows"] == [
        {"start": "17:00", "end": "19:00"},
        {"start": "22:00", "end": "06:00"},
    ]


async def test_get_events(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test daily windows expand into occurrences, including overnight ones."""
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, EVENING, NIGHT
    )

    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            ATTR_ENTITY_ID: entity_id,
            "start_date_time": datetime(2026, 10, 23, tzinfo=dt_util.UTC),
            "end_date_time": datetime(2026, 10, 24, tzinfo=dt_util.UTC),
        },
        blocking=True,
        return_response=True,
    )

    events = response[entity_id]["events"]
    assert [(event["start"], event["end"]) for event in events] == [
        ("2026-10-22T22:00:00+00:00", "2026-10-23T06:00:00+00:00"),
        ("2026-10-23T17:00:00+00:00", "2026-10-23T19:00:00+00:00"),
        ("2026-10-23T22:00:00+00:00", "2026-10-24T06:00:00+00:00"),
    ]


async def test_delete_event(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test deleting an occurrence removes its daily window."""
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, EVENING, NIGHT
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "calendar/event/delete", "entity_id": entity_id, "uid": _uid(0)}
    )

    result = await client.receive_json()
    assert result["success"]
    mock_client.set_schedule.assert_awaited_once_with(MAC, [NIGHT])


async def test_update_event(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """Test updating an occurrence replaces its daily window."""
    entity_id = await _setup_with_windows(
        hass, mock_config_entry, mock_client, EVENING, NIGHT
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "calendar/event/update",
            "entity_id": entity_id,
            "uid": _uid(1),
            "event": {
                "summary": "Power saving",
                "dtstart": "2026-10-23T23:00:00+00:00",
                "dtend": "2026-10-24T05:30:00+00:00",
            },
        }
    )

    result = await client.receive_json()
    assert result["success"]
    mock_client.set_schedule.assert_awaited_once_with(
        MAC, [EVENING, ScheduleWindow(start="23:00", end="05:30")]
    )


@pytest.mark.parametrize("command", ["delete", "update"])
@pytest.mark.parametrize(
    ("uid", "message"),
    [
        ("other:uid", "Invalid ThermoSave schedule event identifier"),
        (f"thermosave:{MAC}:window:x", "Invalid ThermoSave schedule event identifier"),
        (_uid(1), "no longer exists"),
    ],
)
async def test_modify_unknown_event(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    command: str,
    uid: str,
    message: str,
) -> None:
    """Test deleting or updating an unknown occurrence fails."""
    entity_id = await _setup_with_windows(hass, mock_config_entry, mock_client, EVENING)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"calendar/event/{command}",
            "entity_id": entity_id,
            "uid": uid,
            **(
                {
                    "event": {
                        "summary": "Power saving",
                        "dtstart": "2026-10-23T23:00:00+00:00",
                        "dtend": "2026-10-24T05:30:00+00:00",
                    }
                }
                if command == "update"
                else {}
            ),
        }
    )

    result = await client.receive_json()
    assert not result["success"]
    assert message in result["error"]["message"]
    mock_client.set_schedule.assert_not_awaited()
