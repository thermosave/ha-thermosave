"""Data models for pythermosave."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


class ThermosaveMode(StrEnum):
    """Documented ThermoSave operating modes."""

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
    """Status returned by the ThermoSave backend."""

    mac: str
    connection_state: str | None
    last_seen: datetime | None
    power_kw: float | None
    mode: str | None
    relay_state: bool | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """Configuration returned by the ThermoSave backend."""

    timezone: str | None
    windows: tuple[ScheduleWindow, ...]
    mode: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class UnitInfo:
    """Combined status and configuration for one ThermoSave device."""

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

    @classmethod
    def from_parts(
        cls,
        mac: str,
        status: DeviceStatus | None,
        config: DeviceConfig | None,
    ) -> UnitInfo:
        """Combine a device status and configuration into one record."""
        return cls(
            mac=mac,
            connection_state=status.connection_state if status else None,
            last_seen=status.last_seen if status else None,
            power_kw=status.power_kw if status else None,
            mode_status=status.mode if status else None,
            mode_config=config.mode if config else None,
            relay_state=status.relay_state if status else None,
            timezone=config.timezone if config else None,
            windows=config.windows if config else (),
            status_available=status is not None,
            config_available=config is not None,
            status_raw=status.raw if status else None,
            config_raw=config.raw if config else None,
        )

    @property
    def unit_id(self) -> str:
        """Return the stable unit identifier used by older callers."""
        return self.mac

    @property
    def name(self) -> str:
        """Return a human-readable device name."""
        return f"ThermoSave {self.mac}"

    @property
    def is_on(self) -> bool | None:
        """Return the reported relay state."""
        return self.relay_state
