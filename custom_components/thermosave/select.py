"""Select platform for Thermosave."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .entity import ThermosaveEntity
from .pythermosave import ThermosaveError, ThermosaveMode

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ThermosaveConfigEntry
    from .coordinator import ThermosaveDataUpdateCoordinator

_log = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_MODE_OPTIONS = [mode.value for mode in ThermosaveMode]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Thermosave mode selectors."""
    coordinator = entry.runtime_data.coordinator
    known_macs: set[str] = set()

    @callback
    def async_add_new_devices() -> None:
        new_macs = set(coordinator.data) - known_macs
        if not new_macs:
            return
        async_add_entities(
            ThermosaveModeSelect(coordinator, mac) for mac in sorted(new_macs)
        )
        known_macs.update(new_macs)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class ThermosaveModeSelect(ThermosaveEntity, SelectEntity):
    """Select automatic, forced-on, or forced-off operation."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:radiator"
    _attr_options = _MODE_OPTIONS

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "mode")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self.info.mode_config in _MODE_OPTIONS

    @property
    def current_option(self) -> str | None:
        """Return the current operating mode."""
        mode = self.info.mode_config
        return mode if mode in _MODE_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        """Set the selected operating mode."""
        _log.debug(
            "Setting device %s mode to %s",
            self._mac,
            option,
        )
        try:
            await self.coordinator.client.set_mode(self._mac, option)
        except (ThermosaveError, ValueError) as err:
            raise HomeAssistantError(
                f"Unable to set Thermosave mode for {self._mac}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
