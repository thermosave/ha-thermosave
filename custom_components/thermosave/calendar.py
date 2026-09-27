"""Editable daily schedule calendar for Thermosave."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import (
    EVENT_END,
    EVENT_START,
    CalendarEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import ThermosaveEntity
from .pythermosave import ScheduleWindow, ThermosaveError

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ThermosaveConfigEntry
    from .coordinator import ThermosaveDataUpdateCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thermosave schedule calendars."""
    coordinator = entry.runtime_data.coordinator
    known_macs: set[str] = set()

    @callback
    def async_add_new_devices() -> None:
        new_macs = set(coordinator.data) - known_macs
        if not new_macs:
            return
        async_add_entities(
            ThermosaveScheduleCalendar(coordinator, mac) for mac in sorted(new_macs)
        )
        known_macs.update(new_macs)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class ThermosaveScheduleCalendar(ThermosaveEntity, CalendarEntity):
    """Represent and edit the device daily recurring schedule windows."""

    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "schedule")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self.info.config_available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the configured schedule windows."""
        return {
            "schedule_window_count": len(self.info.windows),
            "windows": [
                {"start": window.start, "end": window.end}
                for window in self.info.windows
            ],
        }

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next daily schedule occurrence."""
        now = dt_util.now()
        events = self._events_between(now - timedelta(days=1), now + timedelta(days=2))
        return next((event for event in events if event.end_datetime_local > now), None)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return expanded daily schedule occurrences in a time range."""
        return self._events_between(start_date, end_date)

    async def async_create_event(self, **kwargs: Any) -> None:
        """Append a daily schedule window from a calendar event."""
        window = self._window_from_event(kwargs)
        windows = [*self.info.windows, window]
        await self._async_save_windows(windows)

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete the complete daily window represented by an occurrence."""
        del recurrence_id, recurrence_range
        index = self._window_index(uid)
        windows = list(self.info.windows)
        if index >= len(windows):
            raise HomeAssistantError("The Thermosave schedule window no longer exists")
        del windows[index]
        await self._async_save_windows(windows)

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update the complete daily window represented by an occurrence."""
        del recurrence_id, recurrence_range
        index = self._window_index(uid)
        windows = list(self.info.windows)
        if index >= len(windows):
            raise HomeAssistantError("The Thermosave schedule window no longer exists")
        windows[index] = self._window_from_event(event)
        await self._async_save_windows(windows)

    async def _async_save_windows(self, windows: list[ScheduleWindow]) -> None:
        try:
            await self.coordinator.client.set_schedule(self._mac, windows)
        except (ThermosaveError, ValueError) as err:
            raise HomeAssistantError(
                f"Unable to update the Thermosave schedule for {self._mac}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
        self.async_update_event_listeners()

    def _events_between(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        timezone = self._device_timezone()
        first_day = start_date.astimezone(timezone).date() - timedelta(days=1)
        final_day = end_date.astimezone(timezone).date() + timedelta(days=1)

        events: list[CalendarEvent] = []
        day = first_day
        while day <= final_day:
            for index, window in enumerate(self.info.windows):
                event_start, event_end = self._window_datetimes(day, window, timezone)
                if event_end <= start_date or event_start >= end_date:
                    continue
                events.append(
                    CalendarEvent(
                        start=event_start,
                        end=event_end,
                        summary="Thermosave power saving",
                        description=(
                            "Daily recurring Thermosave schedule window. "
                            "Editing or deleting this occurrence changes the full "
                            "daily schedule window."
                        ),
                        uid=self._window_uid(index),
                        recurrence_id=event_start.isoformat(),
                        rrule="FREQ=DAILY",
                    )
                )
            day += timedelta(days=1)

        events.sort(key=lambda event: event.start_datetime_local)
        return events

    def _device_timezone(self) -> ZoneInfo:
        timezone_name = self.info.timezone or self.hass.config.time_zone
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo(self.hass.config.time_zone)

    @staticmethod
    def _window_datetimes(
        day: date,
        window: ScheduleWindow,
        timezone: ZoneInfo,
    ) -> tuple[datetime, datetime]:
        start_time = time.fromisoformat(window.start)
        end_time = time.fromisoformat(window.end)
        event_start = datetime.combine(day, start_time, tzinfo=timezone)
        end_day = day if end_time > start_time else day + timedelta(days=1)
        event_end = datetime.combine(end_day, end_time, tzinfo=timezone)
        return event_start, event_end

    def _window_from_event(self, event: dict[str, Any]) -> ScheduleWindow:
        start = event.get(EVENT_START)
        end = event.get(EVENT_END)
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise HomeAssistantError(
                "Thermosave schedule entries must have start and end times, "
                "not all-day dates"
            )
        if start.tzinfo is None or end.tzinfo is None:
            raise HomeAssistantError("Schedule start and end must include a timezone")
        if end <= start or end - start > timedelta(days=1):
            raise HomeAssistantError(
                "A Thermosave schedule window must be longer than zero and "
                "at most 24 hours"
            )

        timezone = self._device_timezone()
        local_start = start.astimezone(timezone)
        local_end = end.astimezone(timezone)
        start_value = local_start.strftime("%H:%M")
        end_value = local_end.strftime("%H:%M")
        if start_value == end_value:
            raise HomeAssistantError("Cannot have a zero time window.")
        return ScheduleWindow(start=start_value, end=end_value)

    def _window_uid(self, index: int) -> str:
        return f"thermosave:{self._mac}:window:{index}"

    def _window_index(self, uid: str) -> int:
        prefix = f"thermosave:{self._mac}:window:"
        if not uid.startswith(prefix):
            raise HomeAssistantError("Invalid Thermosave schedule event identifier")
        try:
            return int(uid.removeprefix(prefix))
        except ValueError as err:
            raise HomeAssistantError(
                "Invalid Thermosave schedule event identifier"
            ) from err
