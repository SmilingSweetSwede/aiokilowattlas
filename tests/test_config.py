from aiokilowattlas import DEFAULT_CONFIG, capability_tier, resolve_config


def test_defaults_unchanged_without_incoming():
    assert resolve_config(DEFAULT_CONFIG, None) == DEFAULT_CONFIG
    assert resolve_config(DEFAULT_CONFIG, {}) == DEFAULT_CONFIG


def test_merge_clamps_and_ignores_unknown():
    cfg = resolve_config(
        DEFAULT_CONFIG,
        {
            "config_version": 7,
            "slot_seconds": 60,
            "push_interval_seconds": 1,  # below floor -> 60
            "max_batch": 99999,  # above ceiling -> 5000
            "report_empty_slots": 1,
            "unknown_key": 42,
            "max_sample_interval_seconds": "not-a-number",
        },
    )
    assert cfg["config_version"] == 7
    assert cfg["slot_seconds"] == 60
    assert cfg["push_interval_seconds"] == 60
    assert cfg["max_batch"] == 5000
    assert cfg["report_empty_slots"] is True
    assert "unknown_key" not in cfg
    assert (
        cfg["max_sample_interval_seconds"]
        == DEFAULT_CONFIG["max_sample_interval_seconds"]
    )


def test_slot_must_divide_the_hour():
    cfg = resolve_config(DEFAULT_CONFIG, {"slot_seconds": 700})
    assert cfg["slot_seconds"] == DEFAULT_CONFIG["slot_seconds"]


def test_inverted_interval_bounds_are_reset():
    cfg = resolve_config(
        DEFAULT_CONFIG,
        {"min_sample_interval_seconds": 100, "max_sample_interval_seconds": 5},
    )
    assert (
        cfg["min_sample_interval_seconds"]
        == DEFAULT_CONFIG["min_sample_interval_seconds"]
    )
    assert (
        cfg["max_sample_interval_seconds"]
        == DEFAULT_CONFIG["max_sample_interval_seconds"]
    )


def test_does_not_mutate_inputs():
    base = dict(DEFAULT_CONFIG)
    incoming = {"slot_seconds": 300}
    resolve_config(base, incoming)
    assert base == DEFAULT_CONFIG
    assert incoming == {"slot_seconds": 300}


def test_capability_tier():
    assert capability_tier(1) == "realtime_1s"
    assert capability_tier(5) == "realtime_1s"
    assert capability_tier(30) == "fast_subminute"
    assert capability_tier(60) == "batch_15min"
