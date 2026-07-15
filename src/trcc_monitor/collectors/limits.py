"""Claude rate-limit windows.

Reads the OAuth token from ``~/.claude/.credentials.json`` and GETs
``/api/oauth/usage`` — the same endpoint Claude Code's own ``/usage`` screen
reads. It is a plain authenticated GET: no inference, no tokens, and nothing
charged against the very limits it reports. Poll it as often as you like
(within reason — the endpoint is itself rate-limited server-side).
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import Proxy
from .base import Collector

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def _client(proxy: Proxy, timeout: float) -> httpx.Client:
    if proxy.mode == "none":
        return httpx.Client(trust_env=False, timeout=timeout)
    if proxy.mode == "custom" and proxy.url:
        return httpx.Client(proxy=proxy.url, trust_env=False, timeout=timeout)
    return httpx.Client(trust_env=True, timeout=timeout)  # "env"


def read_credentials(creds_file: str | Path) -> tuple[str, str]:
    """Return (access_token, subscription_type). Raises on missing/invalid file."""
    with open(creds_file) as f:
        oauth = json.load(f)["claudeAiOauth"]
    return oauth["accessToken"], oauth.get("subscriptionType", "")


def fmt_reset(ts: str | float | None, now: float | None = None) -> str | None:
    """Human 'time until reset' like the widget: now / Nm / Nh / Nd."""
    if not ts:
        return None
    try:
        target = int(float(ts))
    except (TypeError, ValueError):
        return str(ts)
    ref = now if now is not None else time.time()
    mins = round((target - ref) / 60)
    if mins < 0:
        return "now"
    if mins < 60:
        return f"{mins}m"
    hours = round(mins / 60)
    if hours < 24:
        return f"{hours}h"
    days = round(hours / 24)
    return f"{days}d"


def _iso_to_unix(value: Any) -> float | None:
    """Parse the endpoint's ISO-8601 ``resets_at`` into unix seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:  # defensive: the API sends an offset, but assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _window(raw: Any, now: float) -> dict[str, Any]:
    """One rate-limit window, in the shape the renderer expects."""
    if not isinstance(raw, dict):
        return {"status": None, "utilization": 0.0, "reset_ts": None, "reset_in": None}
    pct = raw.get("utilization")
    # The endpoint reports 0-100; everything downstream works in 0-1.
    util = float(pct) / 100.0 if isinstance(pct, (int, float)) else 0.0
    reset_ts = _iso_to_unix(raw.get("resets_at"))
    return {
        # This endpoint has no allowed/rejected field (the old header API did),
        # so treat a window as limited exactly when it is used up.
        "status": "limited" if util >= 1.0 else "allowed",
        "utilization": util,
        "reset_ts": reset_ts,
        "reset_in": fmt_reset(reset_ts, now),
    }


# extra_usage.is_enabled -> the widget's overage vocabulary.
_OVERAGE_STATUS = {True: "allowed", False: "rejected"}


def parse_usage_response(
    payload: dict[str, Any], subscription_type: str = "", now: float | None = None
) -> dict[str, Any]:
    """Map ``GET /api/oauth/usage`` onto the dashboard's limits shape.

    Pure; ``now`` is injectable for tests.
    """
    ref = now if now is not None else time.time()
    extra = payload.get("extra_usage") or {}
    return {
        "overage_status": _OVERAGE_STATUS.get(extra.get("is_enabled")),
        "overage_reason": extra.get("disabled_reason"),
        "h5": _window(payload.get("five_hour"), ref),
        "d7": _window(payload.get("seven_day"), ref),
        "plan": subscription_type,
        "updated_at": int(ref),
    }


class LimitsCollector(Collector):
    name = "limits"
    interval = 60.0

    def __init__(
        self,
        credentials_file: Path,
        proxy: Proxy,
        interval: float | None = None,
        timeout: float = 10.0,
        recover_stale_token: bool = True,
    ) -> None:
        super().__init__(interval)
        self._creds_file = credentials_file
        self._proxy = proxy
        self._timeout = timeout
        self._recover = recover_stale_token
        # Latest reset timestamps, exposed so the usage collector can align windows.
        self.h5_reset_ts: float = 0.0
        self.d7_reset_ts: float = 0.0

    def _fetch(self, token: str) -> dict[str, Any] | None:
        """GET the usage payload. None means the token was rejected."""
        req_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        with _client(self._proxy, self._timeout) as client:
            resp = client.get(USAGE_URL, headers=req_headers)
        if resp.status_code in (401, 403):
            return None
        resp.raise_for_status()
        return resp.json()

    def poll(self) -> dict[str, Any]:
        if not self._creds_file.is_file():
            raise FileNotFoundError(
                f"No credentials file at {self._creds_file}"
            )
        token, subscription = read_credentials(self._creds_file)
        payload = self._fetch(token)

        # Token may be stale (e.g. right after boot). Spawn claude briefly to
        # trigger an OAuth refresh, re-read the token, then retry once.
        if payload is None and self._recover:
            try:
                subprocess.run(
                    ["claude", "-p", "x"],
                    timeout=5,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            token, subscription = read_credentials(self._creds_file)
            payload = self._fetch(token)

        if payload is None:
            raise RuntimeError("usage endpoint rejected the OAuth token")

        result = parse_usage_response(payload, subscription)
        # Cache reset timestamps for window alignment.
        for key, attr in (("h5", "h5_reset_ts"), ("d7", "d7_reset_ts")):
            raw = result[key].get("reset_ts")
            setattr(self, attr, float(raw) if raw else 0.0)
        return result
