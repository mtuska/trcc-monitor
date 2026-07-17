"""Codex (OpenAI) rate-limit windows.

Asks the local ``codex app-server`` over JSON-RPC on stdio — the same interface
Codex's own UI uses for its rate-limit display. We never talk to OpenAI
ourselves: the app-server owns the ChatGPT OAuth tokens in ``~/.codex`` and
answers ``account/rateLimits/read``. Costs nothing.

The window is identified by ``windowDurationMins`` rather than a name: 10080
minutes is the weekly limit, 300 the 5-hour one. A plan may report only one.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any

from .base import Collector

WEEKLY_MINS = 10080


def _rpc(timeout: float) -> dict[str, Any]:
    """Run one initialize + rateLimits/read exchange against a fresh app-server.

    stdin is deliberately held open: the server exits on EOF, and the
    rate-limit answer arrives after the initialize reply, so closing stdin
    early (e.g. via communicate()) loses it. A watchdog kills the process if it
    stops talking, which unblocks the readline loop.
    """
    proc = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    watchdog = threading.Timer(timeout, proc.kill)
    watchdog.start()
    try:
        for req in (
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"clientInfo": {"name": "trcc-monitor",
                                       "title": "trcc-monitor",
                                       "version": "0.1.0"}}},
            {"jsonrpc": "2.0", "id": 1,
             "method": "account/rateLimits/read", "params": {}},
        ):
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()

        # The server interleaves unsolicited notifications with responses, so
        # read until our id shows up rather than taking the first line.
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(f"codex app-server: {msg['error']}")
                return msg.get("result") or {}
    except (BrokenPipeError, OSError) as exc:
        raise RuntimeError(f"codex app-server: {exc}") from exc
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
    raise RuntimeError("codex app-server returned no rate-limit response")


def _window(raw: Any) -> dict[str, Any] | None:
    """One rate-limit window in the dashboard's shape, or None."""
    if not isinstance(raw, dict):
        return None
    pct = raw.get("usedPercent")
    if not isinstance(pct, (int, float)):
        return None
    mins = raw.get("windowDurationMins")
    return {
        # usedPercent is 0-100; everything downstream works in 0-1.
        "utilization": float(pct) / 100.0,
        "reset_ts": raw.get("resetsAt"),
        "window_mins": mins,
        "label": _window_label(mins),
    }


def _window_label(mins: Any) -> str:
    if not isinstance(mins, (int, float)) or mins <= 0:
        return "limit"
    if mins % 1440 == 0:
        days = int(mins // 1440)
        return "7-day" if days == 7 else f"{days}-day"
    if mins % 60 == 0:
        return f"{int(mins // 60)}-hour"
    return f"{int(mins)}-min"


def parse_rate_limits(result: dict[str, Any]) -> dict[str, Any]:
    """Map ``account/rateLimits/read`` onto the dashboard's shape. Pure."""
    snap = result.get("rateLimits") or {}
    # Prefer the explicitly-metered "codex" bucket when the server splits them.
    by_id = result.get("rateLimitsByLimitId") or {}
    if isinstance(by_id, dict) and isinstance(by_id.get("codex"), dict):
        snap = by_id["codex"]

    windows = [w for w in (_window(snap.get("primary")),
                           _window(snap.get("secondary"))) if w]
    weekly = next((w for w in windows if w["window_mins"] == WEEKLY_MINS), None)
    credits = snap.get("credits") or {}
    return {
        "plan": snap.get("planType") or "",
        "weekly": weekly,
        "windows": windows,
        "limit_reached": bool(snap.get("rateLimitReachedType")),
        "credits_balance": credits.get("balance"),
        "has_credits": bool(credits.get("hasCredits")),
        "unlimited": bool(credits.get("unlimited")),
        "updated_at": int(time.time()),
    }


class CodexCollector(Collector):
    name = "codex"
    interval = 120.0

    def __init__(self, interval: float | None = None, timeout: float = 20.0) -> None:
        super().__init__(interval)
        self._timeout = timeout

    def poll(self) -> dict[str, Any]:
        return parse_rate_limits(_rpc(self._timeout))
