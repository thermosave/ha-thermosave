"""Water heater platform for ThermoSave."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, UnitOfTemperature
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

# Standard operation modes, so voice assistants and HomeKit understand them.
_MODE_TO_OPERATION = {
    ThermosaveMode.AUTO: STATE_ECO,
    ThermosaveMode.ON: STATE_PERFORMANCE,
    ThermosaveMode.OFF: STATE_OFF,
}
_OPERATION_TO_MODE = {operation: mode for mode, operation in _MODE_TO_OPERATION.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ThermoSave water heaters."""
    coordinator = entry.runtime_data.coordinator
    known_macs: set[str] = set()

    @callback
    def async_add_new_devices() -> None:
        new_macs = set(coordinator.data) - known_macs
        if not new_macs:
            return
        async_add_entities(
            ThermosaveWaterHeater(coordinator, mac) for mac in sorted(new_macs)
        )
        known_macs.update(new_macs)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class ThermosaveWaterHeater(ThermosaveEntity, WaterHeaterEntity):
    """
    Control the device mode as a water heater.

    The device reports no water temperature, so this only exposes the mode.
    """

    _attr_name = None
    _attr_translation_key = "water_heater"
    _attr_supported_features = (
        WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_operation_list = list(_MODE_TO_OPERATION.values())
    # Required by WaterHeaterEntity, although no temperature is reported.
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "water_heater")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self.info.mode_config in _MODE_TO_OPERATION

    @property
    def current_operation(self) -> str | None:
        """Return the operation mode for the configured device mode."""
        return _MODE_TO_OPERATION.get(self.info.mode_config)  # type: ignore[arg-type]

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set the device mode for an operation mode."""
        await self._async_set_mode(_OPERATION_TO_MODE[operation_mode])

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Return the device to its schedule."""
        await self._async_set_mode(ThermosaveMode.AUTO)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Force the device off."""
        await self._async_set_mode(ThermosaveMode.OFF)

    async def _async_set_mode(self, mode: ThermosaveMode) -> None:
        """Write the device mode and refresh with the returned config."""
        _log.debug("Setting device %s mode to %s", self._mac, mode)
        try:
            config = await self.coordinator.client.set_mode(self._mac, mode)
        except (ThermosaveError, ValueError) as err:
            raise HomeAssistantError(
                f"Unable to set ThermoSave mode for {self._mac}: {err}"
            ) from err
        self.coordinator.async_update_config(self._mac, config)
        await self.coordinator.async_request_refresh()
