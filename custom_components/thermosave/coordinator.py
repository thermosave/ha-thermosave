"""Data update coordinator for ThermoSave."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .pythermosave import (
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
    """Coordinate polling of all devices claimed by one account."""

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
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> ThermosaveCoordinatorData:
        try:
            macs = await self.client.list_devices()
            infos = await asyncio.gather(*(self.client.read_info(mac) for mac in macs))
            return dict(zip(macs, infos, strict=True))
        except ThermosaveAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except ThermosaveError as err:
            raise UpdateFailed(f"Error communicating with ThermoSave: {err}") from err
