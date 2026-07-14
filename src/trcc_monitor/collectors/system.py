"""Local system metrics via psutil.

New for trcc-monitor (the KDE desktop got these from Plasma sensors). Provides
CPU %, memory, disk usage, and disk/network throughput rates. Rates are computed
from counter deltas between polls, so the first poll reports zero rates. Short
ring buffers feed the little history graphs in the renderer.
"""
from __future__ import annotations

import collections
import time
from typing import Any

import psutil

from .base import Collector


class SystemCollector(Collector):
    name = "system"
    interval = 2.0

    def __init__(
        self,
        interval: float | None = None,
        disk_path: str = "/",
        history: int = 60,
    ) -> None:
        super().__init__(interval)
        self._disk_path = disk_path
        self._prev_net: Any | None = None
        self._prev_disk: Any | None = None
        self._prev_t: float | None = None
        self._net_up_hist: collections.deque = collections.deque(maxlen=history)
        self._net_down_hist: collections.deque = collections.deque(maxlen=history)
        self._cpu_hist: collections.deque = collections.deque(maxlen=history)
        self._cpu_name = self._read_cpu_name()
        # Prime psutil's internal cpu-percent baseline so the first real read is sane.
        psutil.cpu_percent(interval=None)

    @staticmethod
    def _read_cpu_name() -> str:
        """CPU model name, from /proc/cpuinfo (Linux) or platform fallback."""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        import platform
        return platform.processor() or "CPU"

    @staticmethod
    def _cpu_temp() -> float | None:
        """Best-effort CPU package temperature in °C, or None if unavailable."""
        fn = getattr(psutil, "sensors_temperatures", None)
        if fn is None:
            return None
        try:
            temps = fn()
        except Exception:
            return None
        # Prefer a known CPU sensor; fall back to the first labelled "package".
        for chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
            entries = temps.get(chip)
            if entries:
                for e in entries:
                    if "package" in (e.label or "").lower() or "tctl" in (e.label or "").lower():
                        return e.current
                return entries[0].current
        for entries in temps.values():
            if entries:
                return entries[0].current
        return None

    def poll(self) -> dict[str, Any]:
        now = time.time()
        cpu = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        du = psutil.disk_usage(self._disk_path)
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()

        dt = (now - self._prev_t) if self._prev_t else 0.0

        def rate(cur: int, prev: int | None) -> float:
            if prev is None or dt <= 0:
                return 0.0
            d = cur - prev
            return d / dt if d >= 0 else 0.0  # guard counter resets

        net_up = rate(net.bytes_sent, self._prev_net.bytes_sent if self._prev_net else None)
        net_down = rate(net.bytes_recv, self._prev_net.bytes_recv if self._prev_net else None)
        disk_w = rate(disk.write_bytes, self._prev_disk.write_bytes if self._prev_disk else None) if disk else 0.0
        disk_r = rate(disk.read_bytes, self._prev_disk.read_bytes if self._prev_disk else None) if disk else 0.0

        try:
            load_avg = psutil.getloadavg()
        except (AttributeError, OSError):
            load_avg = None  # not available on this platform

        self._prev_net = net
        self._prev_disk = disk
        self._prev_t = now
        self._cpu_hist.append(cpu)
        self._net_up_hist.append(net_up)
        self._net_down_hist.append(net_down)

        return {
            "cpu_percent": cpu,
            "cpu_cores": psutil.cpu_count(logical=True),
            "cpu_name": self._cpu_name,
            "cpu_temp": self._cpu_temp(),
            "load_avg": load_avg,
            "mem_used": vm.used,
            "mem_total": vm.total,
            "mem_percent": vm.percent,
            "disk_used": du.used,
            "disk_free": du.free,
            "disk_total": du.total,
            "disk_percent": du.percent,
            "net_up_rate": net_up,
            "net_down_rate": net_down,
            "disk_read_rate": disk_r,
            "disk_write_rate": disk_w,
            "cpu_history": list(self._cpu_hist),
            "net_up_history": list(self._net_up_hist),
            "net_down_history": list(self._net_down_hist),
        }
