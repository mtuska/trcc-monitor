"""Wiring: build the collector dashboard from config and link collectors."""
from __future__ import annotations

from .collectors import (
    Dashboard,
    GpuCollector,
    LimitsCollector,
    SessionsCollector,
    StatusCollector,
    SystemCollector,
    UsageCollector,
)
from .config import Config


def build_dashboard(config: Config) -> tuple[Dashboard, dict]:
    """Construct a Dashboard with the enabled collectors.

    Returns (dashboard, collectors) where ``collectors`` maps name → the
    concrete collector instance, so callers can reach collector-specific hooks
    (e.g. feeding rate-limit resets into the usage collector).
    """
    dash = Dashboard()
    collectors: dict = {}

    def enabled(name: str) -> bool:
        return name in config.panels

    if enabled("limits"):
        collectors["limits"] = LimitsCollector(
            config.credentials_file, config.proxy, config.intervals.limits
        )
    if enabled("usage"):
        collectors["usage"] = UsageCollector(
            config.projects_dir, config.intervals.usage
        )
    if enabled("sessions"):
        collectors["sessions"] = SessionsCollector(
            config.projects_dir, config.session_window_s, config.intervals.sessions
        )
    if enabled("status"):
        collectors["status"] = StatusCollector(
            config.proxy, config.intervals.status
        )
    if enabled("system"):
        collectors["system"] = SystemCollector(
            config.intervals.system, disk_path=config.disk_path
        )
    if enabled("gpu"):
        collectors["gpu"] = GpuCollector(config.intervals.gpu)

    for c in collectors.values():
        dash.add(c)

    return dash, collectors


def link_resets(collectors: dict) -> None:
    """Feed the limits collector's reset timestamps into the usage collector.

    Keeps the 5h/7d token sums aligned with the server's utilization windows.
    Safe to call every render tick.
    """
    limits = collectors.get("limits")
    usage = collectors.get("usage")
    if limits is not None and usage is not None:
        usage.set_resets(limits.h5_reset_ts, limits.d7_reset_ts)
