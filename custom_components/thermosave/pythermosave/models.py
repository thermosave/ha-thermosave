"""Data models for pythermosave."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


class ThermosaveMode(StrEnum):
    """Documented Thermosave operating modes."""

    AUTO = "auto"
    ON = "on"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Authentication tokens returned by Amazon Cognito."""

    access_token: str
    refresh_token: str
    expires_at: float | None


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Pending Cognito email OTP challenge."""

    email: str
    session: str


@dataclass(frozen=True, slots=True)
class ScheduleWindow:
    """One configured schedule window."""

    start: str
    end: str


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    """Status returned by the Thermosave backend."""

    mac: str
    connection_state: str | None
    last_seen: datetime | None
    power_kw: float | None
    mode: str | None
    relay_state: bool | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """Configuration returned by the Thermosave backend."""

    timezone: str | None
    windows: tuple[ScheduleWindow, ...]
    mode: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class UnitInfo:
    """Combined status and configuration for one Thermosave device."""

    mac: str
    connection_state: str | None
    last_seen: datetime | None
    power_kw: float | None
    mode_status: str | None
    mode_config: str | None
    relay_state: bool | None
    timezone: str | None
    windows: tuple[ScheduleWindow, ...]
    status_available: bool
    config_available: bool
    status_raw: Mapping[str, Any] | None = None
    config_raw: Mapping[str, Any] | None = None

    @property
    def unit_id(self) -> str:
        """Return the stable unit identifier used by older callers."""
        return self.mac

    @property
    def name(self) -> str:
        """Return a human-readable device name."""
        return f"Thermosave {self.mac}"

    @property
    def is_on(self) -> bool | None:
        """Return the reported relay state."""
        return self.relay_state
