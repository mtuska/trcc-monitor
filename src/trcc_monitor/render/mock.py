"""Synthetic collector snapshots for `preview --mock` and renderer development.

Values mirror the shapes the real collectors produce and roughly match the
numbers in the KDE widget screenshot, so the layout can be designed without a
live Claude session or hardware.
"""
from __future__ import annotations

import math
import time

from ..collectors.base import Snapshot


def _snap(name: str, data) -> Snapshot:
    now = time.time()
    return Snapshot(name=name, data=data, ok=True, updated_at=now,
                    last_attempt=now, error=None)


def snapshots() -> dict[str, Snapshot]:
    now = int(time.time())
    net_up = [40e3 + 260e3 * abs(math.sin(i / 4)) for i in range(60)]
    net_down = [30e3 + 90e3 * abs(math.sin(i / 6 + 1)) for i in range(60)]
    cpu_hist = [4 + 3 * abs(math.sin(i / 5)) for i in range(60)]

    return {
        "limits": _snap("limits", {
            "status": "allowed",
            "overage_status": "rejected",
            "plan": "max",
            "h5": {"status": "allowed", "utilization": 0.15,
                   "reset_ts": str(now + 2 * 3600 + 35 * 60), "reset_in": "3h"},
            "d7": {"status": "allowed", "utilization": 0.48,
                   "reset_ts": str(now + 3 * 86400 + 16 * 3600), "reset_in": "4d"},
            "updated_at": now,
        }),
        "usage": _snap("usage", {
            "today": {"input": 125149, "output": 2799706, "cache_write": 21693915,
                      "cache_read": 789024216, "total": 813642986,
                      "cost": 935.11, "cache_hit": 0.97},
            "window_5h_tokens": 94_000_000,
            "window_7d_tokens": 4_000_000_000,
            "rate_per_hour": 119_000_000,
            "by_model": {"Fable": 490_000_000, "Opus": 287_000_000, "Other": 3_000_000},
            "daily": [1.7e9, 0.45e9, 0.98e9, 0.90e9, 1.76e9, 0.70e9, 0.81e9],
        }),
        "sessions": _snap("sessions", {"agents": 1, "subagents": 0}),
        "status": _snap("status", {
            "indicator": "none", "description": "All Systems Operational",
            "incidents": [], "maintenances": [], "components": [],
        }),
        "gpu": _snap("gpu", {
            "available": True, "vendor": "nvidia", "name": "NVIDIA GeForce RTX 4090",
            "usage_percent": 42.0,
            "vram_used": 5.2 * 2**30, "vram_total": 24.0 * 2**30, "vram_percent": 21.7,
            "temp": 50.0, "power": 220.0,
        }),
        "system": _snap("system", {
            "cpu_percent": 5.5, "cpu_cores": 32, "cpu_temp": 44.0,
            "cpu_name": "AMD Ryzen 9 7950X 16-Core Processor",
            "load_avg": (2.15, 3.42, 2.98),
            "mem_used": 20.6 * 2**30, "mem_total": 61.9 * 2**30, "mem_percent": 33.2,
            "disk_used": 3.6 * 2**40 * 0.86, "disk_free": 521.7 * 2**30,
            "disk_total": 3.6 * 2**40, "disk_percent": 86.0,
            "net_up_rate": 282e3, "net_down_rate": 88e3,
            "disk_read_rate": 0.0, "disk_write_rate": 0.0,
            "cpu_history": cpu_hist,
            "net_up_history": net_up, "net_down_history": net_down,
        }),
    }
