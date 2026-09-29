"""Sensor platform for ThermoSave."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback

from .entity import ThermosaveEntity
from .pythermosave import ThermosaveMode

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ThermosaveConfigEntry
    from .coordinator import ThermosaveDataUpdateCoordinator

PARALLEL_UPDATES = 0

# Power draw above which the element is heating rather than idle with a full tank.
_HEATING_THRESHOLD_KW = 0.1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ThermoSave sensors."""
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
            for entity in (
                ThermosaveStateSensor(coordinator, mac),
                ThermosavePowerSensor(coordinator, mac),
                ThermosaveLastSeenSensor(coordinator, mac),
                ThermosaveTimezoneSensor(coordinator, mac),
            )
        )
        known_macs.update(new_macs)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class ThermosaveStateSensor(ThermosaveEntity, SensorEntity):
    """
    Represent the operational state, as the ThermoSave mobile app shows it.

    Mirrors resolveState() in the app's status_state.dart: forced-off mode wins
    over the relay, and a closed relay drawing no power means the tank is full.
    """

    _attr_translation_key = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:information"
    _attr_options = ["offline", "away", "paused", "ready", "heating"]

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the state sensor."""
        super().__init__(coordinator, mac, "state")

    @property
    def available(self) -> bool:
        """Return whether the state is available."""
        return super().available and self.info.status_available

    @property
    def native_value(self) -> str:
        """Return the current operational state."""
        info = self.info
        if info.connection_state != "online":
            return "offline"
        if info.mode_status == ThermosaveMode.OFF:
            return "away"
        if not info.relay_state:
            # The relay can lag behind a switch to forced-on; the app shows ready.
            return "ready" if info.mode_status == ThermosaveMode.ON else "paused"
        return "heating" if (info.power_kw or 0) > _HEATING_THRESHOLD_KW else "ready"


class ThermosavePowerSensor(ThermosaveEntity, SensorEntity):
    """Represent current device power."""

    _attr_translation_key = "power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "power")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and self.info.status_available
            and self.info.power_kw is not None
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        return self.info.power_kw


class ThermosaveLastSeenSensor(ThermosaveEntity, SensorEntity):
    """Represent when the device was last seen."""

    _attr_translation_key = "last_seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "last_seen")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and self.info.status_available
            and self.info.last_seen is not None
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the sensor value."""
        return self.info.last_seen


class ThermosaveTimezoneSensor(ThermosaveEntity, SensorEntity):
    """Represent the configured device timezone."""

    _attr_translation_key = "timezone"

    def __init__(self, coordinator: ThermosaveDataUpdateCoordinator, mac: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, mac, "timezone")

    @property
    def available(self) -> bool:
        """Return whether the entity is available."""
        return (
            super().available
            and self.info.config_available
            and self.info.timezone is not None
        )

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        return self.info.timezone
