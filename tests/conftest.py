"""Fixtures for ThermoSave tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_EMAIL
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermosave.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.thermosave.pythermosave import (
    AuthSession,
    DeviceConfig,
    DeviceStatus,
    ScheduleWindow,
    TokenSet,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

EMAIL = "user@example.com"
TOKENS = TokenSet("new-access", "new-refresh", 2_000_000_000.0)
MAC = "aa:bb:cc:dd:ee:ff"
LAST_SEEN = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def make_status(mac: str = MAC, **changes: object) -> DeviceStatus:
    """Return a device status for an online device that is heating."""
    values: dict[str, object] = {
        "mac": mac,
        "connection_state": "online",
        "last_seen": LAST_SEEN,
        "power_kw": 2.5,
        "mode": "auto",
        "relay_state": True,
        "raw": {},
    }
    values.update(changes)
    return DeviceStatus(**values)  # type: ignore[arg-type]


def make_config(**changes: object) -> DeviceConfig:
    """Return a device config without schedule windows."""
    values: dict[str, object] = {
        "timezone": "UTC",
        "windows": (),
        "mode": "auto",
        "raw": {},
    }
    values.update(changes)
    return DeviceConfig(**values)  # type: ignore[arg-type]


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration in UTC with whatever the client mock returns."""
    await hass.config.async_set_time_zone("UTC")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def get_entity_id(hass: HomeAssistant, platform: str, key: str, mac: str = MAC) -> str:
    """Return the entity ID of a ThermoSave entity."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{mac}_{key}")
    assert entity_id is not None
    return entity_id


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the custom integration."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry holding expired credentials."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={
            CONF_EMAIL: EMAIL,
            CONF_ACCESS_TOKEN: "old-access",
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_EXPIRES_AT: 1_000_000_000.0,
        },
    )


@pytest.fixture
def mock_flow_client() -> Generator[AsyncMock]:
    """Mock the API client used by the config flow."""
    with patch(
        "custom_components.thermosave.config_flow.ThermosaveClient",
        autospec=True,
    ) as client_class:
        client = client_class.return_value
        client.request_auth_code.return_value = AuthSession(EMAIL, "session")
        client.authenticate.return_value = TOKENS
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent the config flow from setting up the created entry."""
    with patch(
        "custom_components.thermosave.async_setup_entry",
        return_value=True,
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the API client used by the integration."""
    with patch(
        "custom_components.thermosave.ThermosaveClient",
        autospec=True,
    ) as client_class:
        client = client_class.return_value
        client.list_devices.return_value = (MAC,)
        client.get_device_status.return_value = make_status()
        client.get_device_config.return_value = make_config()
        client.set_mode.return_value = make_config(mode="on")
        client.set_schedule.return_value = make_config(
            windows=(ScheduleWindow(start="17:00", end="19:00"),)
        )
        yield client


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> MockConfigEntry:
    """Set up the integration with the default mocked device."""
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry
