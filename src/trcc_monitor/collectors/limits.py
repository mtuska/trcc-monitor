"""Claude API rate-limit windows.

Ported from the KDE widget's ``fetch_limits.sh``. Reads the OAuth token from
``~/.claude/.credentials.json`` and makes a minimal ``POST /v1/messages`` call
(cheapest model, ``max_tokens: 1``) to read the ``anthropic-ratelimit-unified-*``
response headers.

WARNING: every poll is a real API request that counts against usage (one output
token). Keep the interval long — default 5 minutes.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import Proxy
from .base import Collector

API_URL = "https://api.anthropic.com/v1/messages"
PROBE_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}


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


def fmt_reset(ts_str: str | None, now: float | None = None) -> str | None:
    """Human 'time until reset' like the widget: now / Nm / Nh / Nd."""
    if not ts_str:
        return None
    try:
        ts = int(ts_str)
    except (TypeError, ValueError):
        return ts_str
    ref = now if now is not None else time.time()
    mins = round((ts - ref) / 60)
    if mins < 0:
        return "now"
    if mins < 60:
        return f"{mins}m"
    hours = round(mins / 60)
    if hours < 24:
        return f"{hours}h"
    days = round(hours / 24)
    return f"{days}d"


def _to_float(s: str | None) -> float:
    try:
        return float(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def parse_ratelimit_headers(
    headers: dict[str, str], subscription_type: str = "", now: float | None = None
) -> dict[str, Any]:
    """Parse ``anthropic-ratelimit-unified-*`` headers into the widget's shape.

    ``headers`` should be a case-insensitive-ish mapping; keys are lowercased
    here defensively. Pure; ``now`` is injectable for tests.
    """
    h = {k.lower(): v for k, v in headers.items()}

    def get(name: str) -> str | None:
        return h.get(name.lower())

    def window(prefix: str) -> dict[str, Any]:
        reset = get(f"anthropic-ratelimit-unified-{prefix}-reset")
        return {
            "status": get(f"anthropic-ratelimit-unified-{prefix}-status"),
            "utilization": _to_float(
                get(f"anthropic-ratelimit-unified-{prefix}-utilization")
            ),
            "reset_ts": reset,
            "reset_in": fmt_reset(reset, now),
        }

    return {
        "status": get("anthropic-ratelimit-unified-status"),
        "fallback": get("anthropic-ratelimit-unified-fallback"),
        "fallback_pct": get("anthropic-ratelimit-unified-fallback-percentage"),
        "representative_claim": get(
            "anthropic-ratelimit-unified-representative-claim"
        ),
        "overage_status": get("anthropic-ratelimit-unified-overage-status"),
        "overage_reason": get(
            "anthropic-ratelimit-unified-overage-disabled-reason"
        ),
        "h5": window("5h"),
        "d7": window("7d"),
        "plan": subscription_type,
        "updated_at": int(now if now is not None else time.time()),
    }


class LimitsCollector(Collector):
    name = "limits"
    interval = 300.0

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

    def _fetch_headers(self, token: str) -> dict[str, str]:
        req_headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with _client(self._proxy, self._timeout) as client:
            resp = client.post(API_URL, headers=req_headers, json=PROBE_BODY)
        return {
            k: v for k, v in resp.headers.items()
            if k.lower().startswith("anthropic-ratelimit")
        }

    def poll(self) -> dict[str, Any]:
        if not self._creds_file.is_file():
            raise FileNotFoundError(
                f"No credentials file at {self._creds_file}"
            )
        token, subscription = read_credentials(self._creds_file)
        headers = self._fetch_headers(token)

        # Token may be stale (e.g. right after boot). Spawn claude briefly to
        # trigger an OAuth refresh, re-read the token, then retry once.
        if not headers and self._recover:
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
            headers = self._fetch_headers(token)

        if not headers:
            raise RuntimeError("API call failed or no rate-limit headers returned")

        result = parse_ratelimit_headers(headers, subscription)
        # Cache reset timestamps for window alignment.
        for key, attr in (("h5", "h5_reset_ts"), ("d7", "d7_reset_ts")):
            raw = result[key].get("reset_ts")
            try:
                setattr(self, attr, float(raw) if raw else 0.0)
            except (TypeError, ValueError):
                setattr(self, attr, 0.0)
        return result
