"""The ThermoSave integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    COGNITO_BASE_URL,
    COGNITO_CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .coordinator import ThermosaveDataUpdateCoordinator
from .pythermosave import ThermosaveClient, TokenSet

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.WATER_HEATER,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class ThermosaveRuntimeData:
    """Runtime objects associated with a ThermoSave config entry."""

    client: ThermosaveClient
    coordinator: ThermosaveDataUpdateCoordinator


ThermosaveConfigEntry = ConfigEntry[ThermosaveRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
) -> bool:
    """Set up ThermoSave from a config entry."""

    async def async_store_tokens(tokens: TokenSet) -> None:
        """Persist refreshed Cognito tokens in the config entry."""
        new_data: dict[str, Any] = {
            **entry.data,
            CONF_ACCESS_TOKEN: tokens.access_token,
            CONF_REFRESH_TOKEN: tokens.refresh_token,
            CONF_EXPIRES_AT: tokens.expires_at,
        }
        if new_data != dict(entry.data):
            hass.config_entries.async_update_entry(entry, data=new_data)

    client = ThermosaveClient(
        async_get_clientsession(hass),
        cognito_client_id=COGNITO_CLIENT_ID,
        cognito_base_url=COGNITO_BASE_URL,
        api_base_url=API_BASE_URL,
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data.get(CONF_EXPIRES_AT),
        token_update_callback=async_store_tokens,
    )

    coordinator = ThermosaveDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = ThermosaveRuntimeData(
        client=client,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ThermosaveConfigEntry,
) -> bool:
    """Unload a ThermoSave config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
