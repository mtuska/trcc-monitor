"""Local Claude Code token usage and cost.

Ported from the KDE widget's ``fetch_usage.sh``. Purely local filesystem reads
of ``~/.claude/projects/**/*.jsonl`` — no network, no API tokens. Produces
today's tokens/cost, per-model split, cache-hit ratio, a 7-day sparkline, and
per-window token sums used to estimate the (hidden) rate-limit ceilings and
recent burn rate.
"""
from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Collector

# Per-model pricing, $ per token: (input, output, cache-write 5m, cache-read).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus":   (5e-6,  25e-6,  6.25e-6, 0.5e-6),
    "sonnet": (3e-6,  15e-6,  3.75e-6, 0.3e-6),
    "haiku":  (1e-6,  5e-6,   1.25e-6, 0.1e-6),
    "fable":  (10e-6, 50e-6,  12.5e-6, 1.0e-6),
    "mythos": (10e-6, 50e-6,  12.5e-6, 1.0e-6),
}

_FAMILIES = ("opus", "sonnet", "haiku", "fable", "mythos")


def _price(model: str | None) -> tuple[float, float, float, float]:
    m = (model or "").lower()
    for k, v in PRICES.items():
        if k in m:
            return v
    return PRICES["opus"]  # sensible default for unknown Claude models


def _model_family(model: str | None) -> str:
    m = (model or "").lower()
    for k in _FAMILIES:
        if k in m:
            return k.capitalize()
    return "Other"


def _parse_ts(rec: dict) -> float | None:
    ts = rec.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def compute_usage(
    projects_dir: str | os.PathLike,
    now: float,
    h5_reset: float = 0.0,
    d7_reset: float = 0.0,
) -> dict[str, Any]:
    """Scan transcripts and aggregate usage. Pure; ``now`` is injectable for tests.

    ``h5_reset`` / ``d7_reset`` are unix-second reset timestamps from the
    rate-limit headers; when >0 they bound the 5h/7d windows so the token sums
    line up with the server's utilization. When 0, trailing windows from ``now``
    are used.
    """
    proj = os.fspath(projects_dir)

    # Window start = reset - duration (the window is partly elapsed when the
    # reset is in the future). Fall back to a trailing window otherwise.
    h5_start = max(h5_reset - 5 * 3600, now - 5 * 3600) if h5_reset > 0 else now - 5 * 3600
    d7_start = max(d7_reset - 7 * 86400, now - 7 * 86400) if d7_reset > 0 else now - 7 * 86400
    hour_start = now - 3600

    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    week_start = midnight - 6 * 86400  # oldest day shown in the sparkline

    today = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "cost": 0.0}
    w5 = 0
    w7 = 0
    rate = 0
    by_model: dict[str, int] = {}
    daily = [0] * 7

    cutoff = now - 7 * 86400 - 60  # only files touched in the last 7d can matter
    for path in glob.glob(os.path.join(proj, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
        except OSError:
            continue
        try:
            f = open(path, "r", errors="ignore")
        except OSError:
            continue
        with f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message") or {}
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not usage:
                    continue
                t = _parse_ts(rec)
                if t is None or t < cutoff:
                    continue
                i = usage.get("input_tokens", 0) or 0
                o = usage.get("output_tokens", 0) or 0
                cw = usage.get("cache_creation_input_tokens", 0) or 0
                cr = usage.get("cache_read_input_tokens", 0) or 0
                total = i + o + cw + cr

                if t >= d7_start:
                    w7 += total
                if t >= h5_start:
                    w5 += total
                if t >= hour_start:
                    rate += total

                if t >= week_start:
                    di = int((t - week_start) // 86400)
                    if di > 6:
                        di = 6
                    daily[di] += total

                if t >= midnight:
                    today["input"] += i
                    today["output"] += o
                    today["cache_write"] += cw
                    today["cache_read"] += cr
                    pi, po, pcw, pcr = _price(msg.get("model"))
                    today["cost"] += i * pi + o * po + cw * pcw + cr * pcr
                    fam = _model_family(msg.get("model"))
                    by_model[fam] = by_model.get(fam, 0) + total

    today_total = (
        today["input"] + today["output"] + today["cache_write"] + today["cache_read"]
    )
    cache_hit = (
        today["cache_read"] / today_total if today_total > 0 else 0.0
    )
    return {
        "today": {
            "input": today["input"],
            "output": today["output"],
            "cache_write": today["cache_write"],
            "cache_read": today["cache_read"],
            "total": today_total,
            "cost": round(today["cost"], 2),
            "cache_hit": round(cache_hit, 4),
        },
        "window_5h_tokens": w5,
        "window_7d_tokens": w7,
        "rate_per_hour": rate,
        "by_model": by_model,
        "daily": daily,
    }


class UsageCollector(Collector):
    name = "usage"
    interval = 60.0

    def __init__(self, projects_dir: Path, interval: float | None = None) -> None:
        super().__init__(interval)
        self._projects_dir = projects_dir
        # Reset timestamps supplied by the limits collector (see set_resets).
        self._h5_reset = 0.0
        self._d7_reset = 0.0

    def set_resets(self, h5_reset: float, d7_reset: float) -> None:
        """Feed in rate-limit reset timestamps so windows align with the server."""
        self._h5_reset = h5_reset
        self._d7_reset = d7_reset

    def poll(self) -> dict[str, Any]:
        return compute_usage(
            self._projects_dir, time.time(), self._h5_reset, self._d7_reset
        )
