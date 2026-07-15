"""Tests for the /api/oauth/usage parsing."""
from datetime import datetime, timezone

from trcc_monitor.collectors.limits import (
    fmt_reset,
    parse_usage_response,
    read_credentials,
)

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()

# Trimmed from a real GET /api/oauth/usage response. Note utilization is
# reported 0-100 and resets_at is ISO-8601 — not the 0-1 / unix-seconds the
# old rate-limit headers used.
PAYLOAD = {
    "five_hour": {
        "utilization": 3.0,
        "resets_at": "2026-07-15T14:00:00.692270+00:00",
        "limit_dollars": None,
    },
    "seven_day": {
        "utilization": 97.0,
        "resets_at": "2026-07-19T12:00:00.692294+00:00",
        "limit_dollars": None,
    },
    "seven_day_opus": None,
    "extra_usage": {
        "is_enabled": False,
        "disabled_reason": None,
        "used_credits": None,
    },
    "limits": [
        {"kind": "session", "group": "session", "percent": 3,
         "severity": "normal", "is_active": False},
        {"kind": "weekly_all", "group": "weekly", "percent": 97,
         "severity": "critical", "is_active": True},
    ],
}


def test_fmt_reset_buckets():
    now = 1_000_000
    assert fmt_reset(now - 60, now=now) == "now"       # in the past
    assert fmt_reset(now + 30 * 60, now=now) == "30m"
    assert fmt_reset(now + 3 * 3600, now=now) == "3h"
    assert fmt_reset(now + 4 * 86400, now=now) == "4d"
    assert fmt_reset(None) is None
    assert fmt_reset("garbage") == "garbage"


def test_fmt_reset_accepts_str_and_float():
    now = 1_000_000
    assert fmt_reset(str(now + 3600), now=now) == "1h"
    assert fmt_reset(float(now + 3600), now=now) == "1h"


def test_parse_usage_full():
    out = parse_usage_response(PAYLOAD, subscription_type="max", now=NOW)
    assert out["plan"] == "max"
    assert out["updated_at"] == int(NOW)
    # 0-100 from the API must land as 0-1 downstream.
    assert out["h5"]["utilization"] == 0.03
    assert out["d7"]["utilization"] == 0.97
    assert out["h5"]["reset_in"] == "2h"
    assert out["d7"]["reset_in"] == "4d"
    # Neither window is used up, so neither reads as limited.
    assert out["h5"]["status"] == "allowed"
    assert out["d7"]["status"] == "allowed"


def test_reset_ts_is_unix_seconds():
    out = parse_usage_response(PAYLOAD, now=NOW)
    # The renderer derives its live countdown from this, so it must be numeric
    # unix seconds, not the ISO string the endpoint sends.
    assert isinstance(out["h5"]["reset_ts"], float)
    assert out["h5"]["reset_ts"] == NOW + 2 * 3600 + 0.692270


def test_window_limited_when_used_up():
    payload = {"five_hour": {"utilization": 100.0, "resets_at": None}}
    out = parse_usage_response(payload, now=NOW)
    assert out["h5"]["utilization"] == 1.0
    assert out["h5"]["status"] == "limited"


def test_overage_maps_to_widget_vocabulary():
    assert parse_usage_response(PAYLOAD, now=NOW)["overage_status"] == "rejected"
    enabled = {"extra_usage": {"is_enabled": True, "disabled_reason": None}}
    assert parse_usage_response(enabled, now=NOW)["overage_status"] == "allowed"
    # Absent extra_usage must not claim either state.
    assert parse_usage_response({}, now=NOW)["overage_status"] is None


def test_overage_reason_passed_through():
    payload = {"extra_usage": {"is_enabled": False,
                               "disabled_reason": "out_of_credits"}}
    assert parse_usage_response(payload, now=NOW)["overage_reason"] == "out_of_credits"


def test_parse_usage_missing_and_null_windows():
    out = parse_usage_response({"five_hour": None}, now=NOW)
    for key in ("h5", "d7"):
        assert out[key]["utilization"] == 0.0
        assert out[key]["reset_in"] is None
        assert out[key]["reset_ts"] is None
        assert out[key]["status"] is None


def test_parse_usage_tolerates_garbage_reset():
    payload = {"five_hour": {"utilization": 5.0, "resets_at": "not-a-date"}}
    out = parse_usage_response(payload, now=NOW)
    assert out["h5"]["reset_ts"] is None
    assert out["h5"]["reset_in"] is None


def test_read_credentials(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text(
        '{"claudeAiOauth": {"accessToken": "tok-abc", "subscriptionType": "max"}}'
    )
    token, sub = read_credentials(creds)
    assert token == "tok-abc"
    assert sub == "max"
