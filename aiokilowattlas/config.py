"""Server-directed cadence policy: defaults, bounds and the merge rule.

The server sends a `config` document with the device/token, `/contrib/me` and
ingest responses. A client applies it whenever `config_version` increases. The
document is untrusted input from the client's point of view, so every field is
clamped and the two confusable interval bounds are sanity-checked.

Slot size only describes what the server aggregates to. A client that forwards
raw readings does not need it to do its job.
"""

from __future__ import annotations

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 0,
    "slot_seconds": 15 * 60,
    "push_interval_seconds": 15 * 60,
    # Bounds on the sample PERIOD: max_ is the slowest a client may sample,
    # min_ the fastest it may poll a source. Advisory for event-driven clients.
    "max_sample_interval_seconds": 10,
    "min_sample_interval_seconds": 1,
    "max_batch": 500,
    # Off until a server that understands night-gap markers turns it on; an
    # older server would store markers as genuine 0 kW rows.
    "report_empty_slots": False,
    # The raw-reading rate the server would LIKE. Advisory only.
    "raw_sample_interval_seconds": 10,
    # Server channel keys the site owner switched off on kilowattlas.com. A
    # client must not send readings or declarations for them. A list (not a
    # tuple) so the resolved document stays JSON-serialisable.
    "disabled_channels": [],
}

# The server's name for the channel a client sends without a channel key.
SERVER_DEFAULT_CHANNEL_KEY = "default"

MAX_DISABLED_CHANNELS = 32
MAX_CHANNEL_KEY_LENGTH = 64

CONFIG_CLAMPS: dict[str, tuple[int, int]] = {
    "slot_seconds": (60, 3600),
    "push_interval_seconds": (60, 3600),
    "max_sample_interval_seconds": (1, 900),
    "min_sample_interval_seconds": (1, 900),
    "max_batch": (1, 5000),
    "raw_sample_interval_seconds": (1, 900),
}


def resolve_config(
    base: dict[str, Any], incoming: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge a server config document onto `base`, clamped and validated.

    Unknown keys are ignored, missing keys keep their current value, and every
    known numeric field is clamped. `disabled_channels` must be a list; its
    string items are stripped, de-duplicated and sorted, anything else in it
    is dropped, and a non-list value leaves the current set unchanged. The
    result always has a `disabled_channels` list, also when `base` (e.g. a
    config persisted by an older client) has none. Returns a new dict; never
    mutates either argument.
    """
    cfg = dict(base)
    for key, value in (incoming or {}).items():
        if key not in cfg and key not in DEFAULT_CONFIG:
            continue
        if key == "report_empty_slots":
            cfg[key] = bool(value)
            continue
        if key == "disabled_channels":
            if isinstance(value, list):
                cfg[key] = _clean_channel_keys(value)
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if key in CONFIG_CLAMPS:
            lo, hi = CONFIG_CLAMPS[key]
            n = max(lo, min(hi, n))
        cfg[key] = n

    # A slot that does not divide the hour drifts against the UTC grid the
    # server validates against.
    if 3600 % cfg["slot_seconds"] != 0:
        cfg["slot_seconds"] = base["slot_seconds"]

    # An inverted range would clamp the sample interval to nonsense.
    if cfg["min_sample_interval_seconds"] > cfg["max_sample_interval_seconds"]:
        cfg["min_sample_interval_seconds"] = base["min_sample_interval_seconds"]
        cfg["max_sample_interval_seconds"] = base["max_sample_interval_seconds"]

    # Never share the caller's list object with the returned document.
    cfg["disabled_channels"] = list(cfg.get("disabled_channels") or [])
    return cfg


def _clean_channel_keys(value: list[Any]) -> list[str]:
    keys = {
        item.strip()
        for item in value
        if isinstance(item, str)
        and item.strip()
        and len(item.strip()) <= MAX_CHANNEL_KEY_LENGTH
    }
    return sorted(keys)[:MAX_DISABLED_CHANNELS]


def is_channel_disabled(config: dict[str, Any], channel_key: str) -> bool:
    """Whether the owner switched off the channel a client calls `channel_key`.

    The client's default channel (empty key) is `"default"` on the server.
    """
    server_key = channel_key or SERVER_DEFAULT_CHANNEL_KEY
    return server_key in (config.get("disabled_channels") or ())


def capability_tier(sample_interval_seconds: float) -> str:
    """Classify a donor by how often its source delivers a reading."""
    if sample_interval_seconds <= 5:
        return "realtime_1s"
    if sample_interval_seconds < 60:
        return "fast_subminute"
    return "batch_15min"
