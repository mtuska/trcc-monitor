"""Tests for rate-limit header parsing."""
from trcc_monitor.collectors.limits import (
    fmt_reset,
    parse_ratelimit_headers,
    read_credentials,
)


def test_fmt_reset_buckets():
    now = 1_000_000
    assert fmt_reset(str(now - 60), now=now) == "now"       # in the past
    assert fmt_reset(str(now + 30 * 60), now=now) == "30m"
    assert fmt_reset(str(now + 3 * 3600), now=now) == "3h"
    assert fmt_reset(str(now + 4 * 86400), now=now) == "4d"
    assert fmt_reset(None) is None
    assert fmt_reset("garbage") == "garbage"


def test_parse_headers_full():
    now = 1_700_000_000
    headers = {
        "anthropic-ratelimit-unified-status": "allowed",
        "anthropic-ratelimit-unified-fallback": "false",
        "anthropic-ratelimit-unified-overage-status": "rejected",
        "anthropic-ratelimit-unified-overage-disabled-reason": "org_level_disabled",
        "anthropic-ratelimit-unified-5h-status": "allowed",
        "anthropic-ratelimit-unified-5h-utilization": "0.2",
        "anthropic-ratelimit-unified-5h-reset": str(now + 7200),
        "anthropic-ratelimit-unified-7d-status": "allowed",
        "anthropic-ratelimit-unified-7d-utilization": "0.49",
        "anthropic-ratelimit-unified-7d-reset": str(now + 4 * 86400),
    }
    out = parse_ratelimit_headers(headers, subscription_type="max", now=now)
    assert out["status"] == "allowed"
    assert out["plan"] == "max"
    assert out["overage_status"] == "rejected"
    assert out["h5"]["utilization"] == 0.2
    assert out["h5"]["reset_in"] == "2h"
    assert out["d7"]["utilization"] == 0.49
    assert out["d7"]["reset_in"] == "4d"


def test_parse_headers_case_insensitive():
    out = parse_ratelimit_headers(
        {"Anthropic-RateLimit-Unified-Status": "allowed"}, now=0
    )
    assert out["status"] == "allowed"


def test_parse_headers_missing_fields():
    out = parse_ratelimit_headers({}, now=0)
    assert out["status"] is None
    assert out["h5"]["utilization"] == 0.0
    assert out["h5"]["reset_in"] is None


def test_read_credentials(tmp_path):
    creds = tmp_path / ".credentials.json"
    creds.write_text(
        '{"claudeAiOauth": {"accessToken": "tok-abc", "subscriptionType": "max"}}'
    )
    token, sub = read_credentials(creds)
    assert token == "tok-abc"
    assert sub == "max"
