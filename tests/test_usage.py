"""Tests for the usage transcript parser."""
import json
import os
import time

from trcc_monitor.collectors.usage import compute_usage, _model_family, _price


def _write_record(f, ts_iso, model, input_t=0, output_t=0, cw=0, cr=0):
    f.write(json.dumps({
        "timestamp": ts_iso,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_t,
                "output_tokens": output_t,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
            },
        },
    }) + "\n")


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


def test_empty_dir(tmp_path):
    out = compute_usage(tmp_path, now=time.time())
    assert out["today"]["total"] == 0
    assert out["window_5h_tokens"] == 0
    assert out["daily"] == [0] * 7
    assert out["today"]["cache_hit"] == 0.0


def test_today_totals_and_cost(tmp_path):
    now = time.time()
    proj = tmp_path / "myproj"
    proj.mkdir()
    with open(proj / "a.jsonl", "w") as f:
        # 10 min ago, today: haiku, mixed token types
        _write_record(f, _iso(now - 600), "claude-haiku-4-5",
                      input_t=100, output_t=50, cw=200, cr=800)
    out = compute_usage(proj, now=now)
    t = out["today"]
    assert t["input"] == 100
    assert t["output"] == 50
    assert t["cache_write"] == 200
    assert t["cache_read"] == 800
    assert t["total"] == 1150
    # cache_hit = 800 / 1150, rounded to 4 decimals by the collector
    assert t["cache_hit"] == round(800 / 1150, 4)
    # cost = haiku prices
    pi, po, pcw, pcr = _price("claude-haiku-4-5")
    expected = 100 * pi + 50 * po + 200 * pcw + 800 * pcr
    assert abs(t["cost"] - round(expected, 2)) < 0.01


def test_window_and_rate_boundaries(tmp_path):
    now = time.time()
    proj = tmp_path / "p"
    proj.mkdir()
    with open(proj / "a.jsonl", "w") as f:
        _write_record(f, _iso(now - 30 * 60), "opus", output_t=10)     # 30m: in 1h, 5h, 7d
        _write_record(f, _iso(now - 3 * 3600), "opus", output_t=100)   # 3h: in 5h, 7d, not 1h
        _write_record(f, _iso(now - 6 * 86400), "opus", output_t=1000) # 6d: only 7d
    out = compute_usage(proj, now=now)
    assert out["rate_per_hour"] == 10
    assert out["window_5h_tokens"] == 110
    assert out["window_7d_tokens"] == 1110


def test_reset_bounded_windows(tmp_path):
    now = time.time()
    proj = tmp_path / "p"
    proj.mkdir()
    # A record 4h50m ago. With a trailing 5h window it's included; but if the 5h
    # reset is 20min from now, the window started 4h40m ago and excludes it.
    with open(proj / "a.jsonl", "w") as f:
        _write_record(f, _iso(now - (4 * 3600 + 50 * 60)), "opus", output_t=42)
    trailing = compute_usage(proj, now=now)
    assert trailing["window_5h_tokens"] == 42
    bounded = compute_usage(proj, now=now, h5_reset=now + 20 * 60)
    assert bounded["window_5h_tokens"] == 0


def test_per_model_split(tmp_path):
    now = time.time()
    proj = tmp_path / "p"
    proj.mkdir()
    with open(proj / "a.jsonl", "w") as f:
        _write_record(f, _iso(now - 60), "claude-opus-4-8", output_t=100)
        _write_record(f, _iso(now - 60), "claude-fable-5", output_t=200)
        _write_record(f, _iso(now - 60), "some-unknown-model", output_t=5)
    out = compute_usage(proj, now=now)
    assert out["by_model"]["Opus"] == 100
    assert out["by_model"]["Fable"] == 200
    assert out["by_model"]["Other"] == 5


def test_malformed_lines_skipped(tmp_path):
    now = time.time()
    proj = tmp_path / "p"
    proj.mkdir()
    with open(proj / "a.jsonl", "w") as f:
        f.write("not json at all\n")
        f.write(json.dumps({"no": "usage here"}) + "\n")
        _write_record(f, _iso(now - 60), "haiku", output_t=7)
        f.write('{"message": {"usage": null}}\n')
    out = compute_usage(proj, now=now)
    assert out["today"]["output"] == 7


def test_model_family():
    assert _model_family("claude-fable-5") == "Fable"
    assert _model_family("claude-3-5-sonnet") == "Sonnet"
    assert _model_family(None) == "Other"
    assert _model_family("gpt-4") == "Other"
