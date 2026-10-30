from aiokilowattlas import (
    DEFAULT_CONFIG,
    SERVER_DEFAULT_CHANNEL_KEY,
    capability_tier,
    is_channel_disabled,
    resolve_config,
)


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


def test_disabled_channels_default_empty():
    assert DEFAULT_CONFIG["disabled_channels"] == []
    cfg = resolve_config(DEFAULT_CONFIG, None)
    assert cfg["disabled_channels"] == []
    assert cfg["disabled_channels"] is not DEFAULT_CONFIG["disabled_channels"]


def test_disabled_channels_cleaned():
    cfg = resolve_config(
        DEFAULT_CONFIG,
        {
            "disabled_channels": [
                " grid",
                "battery",
                "grid",
                7,
                None,
                "",
                "   ",
                "x" * 65,
                "default",
            ]
        },
    )
    assert cfg["disabled_channels"] == ["battery", "default", "grid"]


def test_disabled_channels_capped():
    keys = [f"k{i:03d}" for i in range(50)]
    cfg = resolve_config(DEFAULT_CONFIG, {"disabled_channels": keys})
    assert cfg["disabled_channels"] == keys[:32]


def test_disabled_channels_non_list_keeps_current():
    base = resolve_config(DEFAULT_CONFIG, {"disabled_channels": ["grid"]})
    for bad in (None, "grid", {"grid": 1}, 3, ("battery",)):
        assert resolve_config(base, {"disabled_channels": bad})[
            "disabled_channels"
        ] == ["grid"]
    assert resolve_config(base, {"disabled_channels": []})["disabled_channels"] == []


def test_disabled_channels_copied_not_shared():
    base = resolve_config(DEFAULT_CONFIG, {"disabled_channels": ["grid"]})
    cfg = resolve_config(base, {"config_version": 2})
    assert cfg["disabled_channels"] == ["grid"]
    assert cfg["disabled_channels"] is not base["disabled_channels"]
    incoming_list = ["battery"]
    cfg = resolve_config(base, {"disabled_channels": incoming_list})
    cfg["disabled_channels"].append("grid")
    assert incoming_list == ["battery"]
    assert base["disabled_channels"] == ["grid"]


def test_disabled_channels_on_legacy_base_without_key():
    legacy = {k: v for k, v in DEFAULT_CONFIG.items() if k != "disabled_channels"}
    assert resolve_config(legacy, None)["disabled_channels"] == []
    cfg = resolve_config(legacy, {"disabled_channels": ["grid"]})
    assert cfg["disabled_channels"] == ["grid"]


def test_is_channel_disabled():
    cfg = resolve_config(DEFAULT_CONFIG, {"disabled_channels": ["default", "grid"]})
    assert SERVER_DEFAULT_CHANNEL_KEY == "default"
    assert is_channel_disabled(cfg, "")
    assert is_channel_disabled(cfg, "default")
    assert is_channel_disabled(cfg, "grid")
    assert not is_channel_disabled(cfg, "battery")
    assert not is_channel_disabled(DEFAULT_CONFIG, "")
    assert not is_channel_disabled({}, "grid")
