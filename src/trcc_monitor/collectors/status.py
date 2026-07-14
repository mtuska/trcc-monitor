"""Claude service status and incidents.

Ported from the KDE widget's ``fetch_status.sh``. Polls the public Statuspage
summary (``status.claude.com/api/v2/summary.json``) — unauthenticated and free;
it does NOT burn API tokens.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import Proxy
from .base import Collector

STATUS_URL = "https://status.claude.com/api/v2/summary.json"


def _client(proxy: Proxy, timeout: float) -> httpx.Client:
    if proxy.mode == "none":
        return httpx.Client(trust_env=False, timeout=timeout)
    if proxy.mode == "custom" and proxy.url:
        return httpx.Client(proxy=proxy.url, trust_env=False, timeout=timeout)
    return httpx.Client(trust_env=True, timeout=timeout)


def parse_summary(body: dict) -> dict[str, Any]:
    """Reduce the Statuspage summary to the fields the widget shows. Pure."""
    st = body.get("status", {}) or {}

    incidents = [
        {
            "name": it.get("name", ""),
            "impact": it.get("impact", ""),
            "status": it.get("status", ""),
            "shortlink": it.get("shortlink", ""),
        }
        for it in (body.get("incidents") or [])
    ]

    maintenances = [
        {
            "name": m.get("name", ""),
            "status": m.get("status", ""),
            "scheduled_for": m.get("scheduled_for", ""),
            "scheduled_until": m.get("scheduled_until", ""),
        }
        for m in (body.get("scheduled_maintenances") or [])
        if (m.get("status") or "").lower() != "completed"
    ]

    components = [
        {"name": c.get("name", ""), "status": c.get("status", "")}
        for c in (body.get("components") or [])
        if not c.get("group")  # skip group headers, keep leaf components
    ]

    return {
        "indicator": st.get("indicator", ""),
        "description": st.get("description", ""),
        "incidents": incidents,
        "maintenances": maintenances,
        "components": components,
    }


class StatusCollector(Collector):
    name = "status"
    interval = 120.0

    def __init__(
        self, proxy: Proxy, interval: float | None = None, timeout: float = 10.0
    ) -> None:
        super().__init__(interval)
        self._proxy = proxy
        self._timeout = timeout

    def poll(self) -> dict[str, Any]:
        with _client(self._proxy, self._timeout) as client:
            resp = client.get(STATUS_URL)
            resp.raise_for_status()
            body = resp.json()
        return parse_summary(body)
