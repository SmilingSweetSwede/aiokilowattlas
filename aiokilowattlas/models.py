"""Typed views of the API's JSON documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class RejectedSample:
    """One reading the server refused, with its machine-readable reason."""

    ts: str
    reason: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one ingest call."""

    accepted: int
    rejected: list[RejectedSample] = field(default_factory=list)
    config: dict[str, Any] | None = None
