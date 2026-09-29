"""Shared ThermoSave entity helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ThermosaveDataUpdateCoordinator

if TYPE_CHECKING:
    from .pythermosave import UnitInfo


class ThermosaveEntity(CoordinatorEntity[ThermosaveDataUpdateCoordinator]):
    """Base entity for one ThermoSave device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ThermosaveDataUpdateCoordinator,
        mac: str,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=f"ThermoSave {mac}",
            manufacturer="ThermoSave",
        )

    @property
    def info(self) -> UnitInfo:
        """Return cached data for this entity's device."""
        return self.coordinator.data[self._mac]

    @property
    def available(self) -> bool:
        """Return whether the account poll still contains this device."""
        return super().available and self._mac in self.coordinator.data
