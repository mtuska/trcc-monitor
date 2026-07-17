"""Tests for the codex app-server rate-limit parsing."""
from trcc_monitor.collectors.codex import (
    WEEKLY_MINS,
    _window_label,
    parse_rate_limits,
)

# Trimmed from a real account/rateLimits/read response.
RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "primary": {"usedPercent": 15, "windowDurationMins": 10080,
                    "resetsAt": 1784845375},
        "secondary": None,
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "individualLimit": None,
        "planType": "plus",
        "rateLimitReachedType": None,
    },
    "rateLimitsByLimitId": {
        "codex": {
            "primary": {"usedPercent": 15, "windowDurationMins": 10080,
                        "resetsAt": 1784845375},
            "secondary": None,
            "planType": "plus",
            "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        }
    },
}


def test_parse_weekly_window():
    out = parse_rate_limits(RESULT)
    assert out["plan"] == "plus"
    # usedPercent is 0-100 from the server; downstream works in 0-1.
    assert out["weekly"]["utilization"] == 0.15
    assert out["weekly"]["reset_ts"] == 1784845375
    assert out["weekly"]["label"] == "7-day"
    assert out["limit_reached"] is False
    assert out["has_credits"] is False


def test_weekly_selected_by_duration_not_position():
    # The weekly window must be found by its 10080-minute duration even when it
    # arrives as `secondary` rather than `primary`.
    result = {"rateLimits": {
        "primary": {"usedPercent": 40, "windowDurationMins": 300,
                    "resetsAt": 100},
        "secondary": {"usedPercent": 7, "windowDurationMins": WEEKLY_MINS,
                      "resetsAt": 200},
    }}
    out = parse_rate_limits(result)
    assert out["weekly"]["utilization"] == 0.07
    assert out["weekly"]["reset_ts"] == 200
    assert len(out["windows"]) == 2


def test_no_weekly_window_is_none():
    result = {"rateLimits": {
        "primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1},
        "secondary": None,
    }}
    out = parse_rate_limits(result)
    assert out["weekly"] is None
    assert len(out["windows"]) == 1


def test_limit_reached_flag():
    result = {"rateLimits": {
        "primary": {"usedPercent": 100, "windowDurationMins": WEEKLY_MINS,
                    "resetsAt": 1},
        "rateLimitReachedType": "rate_limit_reached",
    }}
    out = parse_rate_limits(result)
    assert out["limit_reached"] is True
    assert out["weekly"]["utilization"] == 1.0


def test_empty_and_missing_payloads():
    out = parse_rate_limits({})
    assert out["weekly"] is None
    assert out["windows"] == []
    assert out["plan"] == ""
    # A window with no usedPercent is unusable, not a zero reading.
    assert parse_rate_limits({"rateLimits": {"primary": {}}})["windows"] == []


def test_window_labels():
    assert _window_label(10080) == "7-day"
    assert _window_label(300) == "5-hour"
    assert _window_label(1440) == "1-day"
    assert _window_label(30) == "30-min"
    assert _window_label(None) == "limit"


def test_find_codex_bin_prefers_explicit_override(tmp_path):
    from trcc_monitor.collectors.codex import find_codex_bin
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert find_codex_bin(str(fake)) == str(fake)


def test_find_codex_bin_rejects_bad_override(tmp_path):
    import pytest
    from trcc_monitor.collectors.codex import find_codex_bin
    with pytest.raises(RuntimeError, match="not executable"):
        find_codex_bin(str(tmp_path / "nope"))


def test_find_codex_bin_falls_back_off_path(tmp_path, monkeypatch):
    # A systemd user service's PATH often misses Homebrew et al, so an empty
    # PATH must still find the CLI via the known install roots.
    from trcc_monitor.collectors import codex as mod
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(mod, "_FALLBACK_BINS", (str(fake),))
    assert mod.find_codex_bin() == str(fake)


def test_find_codex_bin_error_is_actionable(monkeypatch):
    import pytest
    from trcc_monitor.collectors import codex as mod
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(mod, "_FALLBACK_BINS", ())
    with pytest.raises(RuntimeError, match="codex_bin"):
        mod.find_codex_bin()
