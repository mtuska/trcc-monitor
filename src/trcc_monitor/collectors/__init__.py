"""Data collectors for trcc-monitor.

Each collector runs on its own cadence (see :mod:`.base`) and produces a plain
dict payload. Parsing logic is factored into module-level pure functions so it
can be unit-tested without threads or I/O.
"""
from .base import Collector, CollectorRunner, Dashboard, Snapshot
from .codex import CodexCollector
from .gpu import GpuCollector
from .limits import LimitsCollector
from .sessions import SessionsCollector
from .status import StatusCollector
from .system import SystemCollector
from .usage import UsageCollector

__all__ = [
    "Collector",
    "CollectorRunner",
    "Dashboard",
    "Snapshot",
    "CodexCollector",
    "GpuCollector",
    "LimitsCollector",
    "SessionsCollector",
    "StatusCollector",
    "SystemCollector",
    "UsageCollector",
]
