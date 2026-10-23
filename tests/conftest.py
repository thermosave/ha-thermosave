"""Fixtures for ThermoSave tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_EMAIL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermosave.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.thermosave.pythermosave import AuthSession, TokenSet

if TYPE_CHECKING:
    from collections.abc import Generator

EMAIL = "user@example.com"
TOKENS = TokenSet("new-access", "new-refresh", 2_000_000_000.0)


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
