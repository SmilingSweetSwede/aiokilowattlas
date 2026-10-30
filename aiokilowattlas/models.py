"""Typed views of the API's JSON documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Measurement kinds a channel may declare at creation. Only gross_production is
# ever summed as production by the server; the rest are stored, shown to the
# owner and drawn on the map, but kept out of every generation figure.
KIND_GROSS_PRODUCTION = "gross_production"
KIND_NET_EXPORT = "net_export"  # grid connection point, positive = export
KIND_CONSUMPTION = "consumption"
KIND_BATTERY_POWER = "battery_power"  # positive = discharge (out of the battery)
KIND_BATTERY_SOC = "battery_soc"  # percent 0-100, carried in power_kw
# Loads (0.3.0): kW drawn by one appliance, never production and never
# negative; the server rejects values below zero.
KIND_EV_CHARGER_POWER = "ev_charger_power"  # positive = car charging
KIND_HEAT_PUMP_POWER = "heat_pump_power"  # electrical input incl. auxiliary heater
# 0.5.0: the Home Assistant Energy dashboard's own model.
# Grid flow in the Energy dashboard's sign: positive = import, negative =
# export. Declarable only; the server stores it as net_export, sign flipped.
KIND_GRID_POWER = "grid_power"
# One device from the Energy dashboard's device list: a load in kW, >= 0.
# Declare it with a "name" so the owner sees which device it is.
KIND_DEVICE_POWER = "device_power"
MEASUREMENT_KINDS = frozenset(
    {
        KIND_GROSS_PRODUCTION,
        KIND_NET_EXPORT,
        KIND_GRID_POWER,
        KIND_CONSUMPTION,
        KIND_BATTERY_POWER,
        KIND_BATTERY_SOC,
        KIND_EV_CHARGER_POWER,
        KIND_HEAT_PUMP_POWER,
        KIND_DEVICE_POWER,
    }
)


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """Response of the device-code request."""

    device_code: str
    user_code: str
    verification_uri: str
    interval: int = 5
    expires_in: int = 900

    @property
    def verification_uri_complete(self) -> str:
        """The verification page with the user code prefilled."""
        return f"{self.verification_uri}?user_code={self.user_code}"


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """Response of a successful token poll."""

    token: str
    site_id: int
    config: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SiteInfo:
    """What `/contrib/me` says about the site a token belongs to."""

    site_id: int
    name: str
    capacity_kw: float | None = None
    config: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SiteDetails:
    """The owner's description of the installation, as last saved anywhere.

    `details` is the server's fields as they are; a save sends them back with
    `revision`, so a change made elsewhere in between is noticed.
    """

    details: dict[str, Any]
    revision: str


@dataclass(frozen=True, slots=True)
class RejectedSample:
    """One reading the server refused, with its machine-readable reason.

    `channel_key` is empty for the default channel and on servers that predate
    multi-channel rejections.
    """

    ts: str
    reason: str
    channel_key: str = ""


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one ingest call."""

    accepted: int
    rejected: list[RejectedSample] = field(default_factory=list)
    config: dict[str, Any] | None = None
