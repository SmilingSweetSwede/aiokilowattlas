"""Async client for the Kilowattlas contributed-solar API."""

from .client import DEFAULT_BASE_URL, KilowattlasClient
from .config import CONFIG_CLAMPS, DEFAULT_CONFIG, capability_tier, resolve_config
from .exceptions import (
    AuthorizationExpired,
    AuthorizationPending,
    KilowattlasAuthError,
    KilowattlasConnectionError,
    KilowattlasError,
    KilowattlasResponseError,
)
from .models import (
    KIND_BATTERY_POWER,
    KIND_BATTERY_SOC,
    KIND_CONSUMPTION,
    KIND_GROSS_PRODUCTION,
    KIND_NET_EXPORT,
    MEASUREMENT_KINDS,
    DeviceCode,
    IngestResult,
    RejectedSample,
    SiteInfo,
    TokenGrant,
)

__version__ = "0.2.0"

__all__ = [
    "CONFIG_CLAMPS",
    "DEFAULT_BASE_URL",
    "DEFAULT_CONFIG",
    "AuthorizationExpired",
    "AuthorizationPending",
    "DeviceCode",
    "IngestResult",
    "KIND_BATTERY_POWER",
    "KIND_BATTERY_SOC",
    "KIND_CONSUMPTION",
    "KIND_GROSS_PRODUCTION",
    "KIND_NET_EXPORT",
    "MEASUREMENT_KINDS",
    "KilowattlasAuthError",
    "KilowattlasClient",
    "KilowattlasConnectionError",
    "KilowattlasError",
    "KilowattlasResponseError",
    "RejectedSample",
    "SiteInfo",
    "TokenGrant",
    "capability_tier",
    "resolve_config",
]
