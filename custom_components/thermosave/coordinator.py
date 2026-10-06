"""Data update coordinator for ThermoSave."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONFIG_UPDATE_INTERVAL,
    DEVICES_UPDATE_INTERVAL,
    DOMAIN,
    STATUS_UPDATE_INTERVAL,
)
from .pythermosave import (
    DeviceConfig,
    ThermosaveAuthenticationError,
    ThermosaveClient,
    ThermosaveError,
    UnitInfo,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ThermosaveCoordinatorData = dict[str, UnitInfo]


class ThermosaveDataUpdateCoordinator(DataUpdateCoordinator[ThermosaveCoordinatorData]):
    """
    Coordinate polling of all devices claimed by one account.

    Status is polled on every update. The device list and per-device configs
    change rarely, so they are cached and only refetched once stale.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: ThermosaveClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=STATUS_UPDATE_INTERVAL,
        )
        self.client = client
        self._macs: tuple[str, ...] | None = None
        self._macs_fetched_at = 0.0
        self._configs: dict[str, DeviceConfig | None] = {}
        self._config_fetched_at: dict[str, float] = {}

    def async_update_config(self, mac: str, config: DeviceConfig | None) -> None:
        """Store a freshly read config, e.g. one returned by a write."""
        self._configs[mac] = config
        self._config_fetched_at[mac] = time.monotonic()

    async def _async_update_data(self) -> ThermosaveCoordinatorData:
        try:
            macs = await self._async_get_macs()
            stale = [mac for mac in macs if self._config_is_stale(mac)]
            statuses, configs = await asyncio.gather(
                asyncio.gather(*(self.client.get_device_status(mac) for mac in macs)),
                asyncio.gather(*(self.client.get_device_config(mac) for mac in stale)),
            )
        except ThermosaveAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except ThermosaveError as err:
            raise UpdateFailed(f"Error communicating with ThermoSave: {err}") from err

        for mac, config in zip(stale, configs, strict=True):
            self.async_update_config(mac, config)

        return {
            mac: UnitInfo.from_parts(mac, status, self._configs[mac])
            for mac, status in zip(macs, statuses, strict=True)
        }

    async def _async_get_macs(self) -> tuple[str, ...]:
        now = time.monotonic()
        if (
            self._macs is None
            or now - self._macs_fetched_at >= DEVICES_UPDATE_INTERVAL.total_seconds()
        ):
            self._macs = await self.client.list_devices()
            self._macs_fetched_at = now
            for mac in set(self._configs) - set(self._macs):
                del self._configs[mac]
                del self._config_fetched_at[mac]
        return self._macs

    def _config_is_stale(self, mac: str) -> bool:
        fetched_at = self._config_fetched_at.get(mac)
        return (
            fetched_at is None
            or time.monotonic() - fetched_at >= CONFIG_UPDATE_INTERVAL.total_seconds()
        )
