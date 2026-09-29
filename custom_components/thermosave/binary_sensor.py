"""Binary sensor platform for ThermoSave."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback

from .entity import ThermosaveEntity

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
    """Set up ThermoSave binary sensors."""
    coordinator = entry.runtime_data.coordinator
    known_macs: set[str] = set()

    @callback
    def async_add_new_devices() -> None:
        new_macs = set(coordinator.data) - known_macs
        if not new_macs:
            return
        async_add_entities(
            entity
            for mac in sorted(new_macs)
            for entity in (ThermosaveOnlineBinarySensor(coordinator, mac),)
        )
        known_macs.update(new_macs)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class ThermosaveOnlineBinarySensor(ThermosaveEntity, BinarySensorEntity):
    """Represent the device to ThermoSave backend connection state."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "online")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return super().available and self.info.status_available

    @property
    def is_on(self) -> bool | None:
        """Return whether the device is online."""
        if not self.info.status_available:
            return None
        return self.info.connection_state == "online"
