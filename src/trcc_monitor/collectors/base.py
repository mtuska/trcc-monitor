"""Collector framework.

Each collector runs on its own cadence in its own thread and publishes a
thread-safe :class:`Snapshot`. A snapshot always keeps the last *good* data
(so the display shows real numbers even while a refresh is failing) alongside
freshness/error state, so the renderer can flag staleness. A failing poll never
kills the thread — the loop just records the error and tries again next tick.
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    """Immutable view of a collector's state at a moment in time."""

    name: str
    data: Any | None            # last successful payload (None until first success)
    ok: bool                    # did the most recent poll succeed?
    updated_at: float           # monotonic-independent wall time of last good data (0 = never)
    last_attempt: float         # wall time of the most recent poll attempt
    error: str | None           # message from the most recent failed poll, else None

    def age(self, now: float | None = None) -> float:
        """Seconds since the last *good* data. inf if never succeeded."""
        if self.updated_at <= 0:
            return float("inf")
        return (now if now is not None else time.time()) - self.updated_at

    def is_stale(self, max_age: float, now: float | None = None) -> bool:
        return self.age(now) > max_age


class Collector(ABC):
    """A single data source. Subclasses implement :meth:`poll`."""

    #: short identifier, matches config panel names
    name: str = "collector"
    #: default refresh interval in seconds (overridden per-instance)
    interval: float = 60.0

    def __init__(self, interval: float | None = None) -> None:
        if interval is not None:
            self.interval = interval

    @abstractmethod
    def poll(self) -> Any:
        """Fetch fresh data. May raise; the runner catches and records it."""
        raise NotImplementedError


class CollectorRunner:
    """Runs one collector in a background thread, exposing its latest snapshot."""

    def __init__(self, collector: Collector) -> None:
        self._collector = collector
        self._lock = threading.Lock()
        self._data: Any | None = None
        self._updated_at: float = 0.0
        self._last_attempt: float = 0.0
        self._ok: bool = False
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return self._collector.name

    def poll_once(self) -> Snapshot:
        """Run a single poll synchronously (used by ``check`` and tests)."""
        self._last_attempt = time.time()
        try:
            data = self._collector.poll()
        except Exception as e:  # noqa: BLE001 — a collector must never crash the loop
            self._ok = False
            error = f"{type(e).__name__}: {e}"
            # Log on the rising edge only: a permanently broken collector would
            # otherwise flood the journal, but staying silent means its panel
            # reads "no data" with nothing anywhere explaining why.
            if error != self._error:
                log.warning("collector %s failed: %s", self._collector.name, error)
            self._error = error
        else:
            with self._lock:
                self._data = data
                self._updated_at = time.time()
            if not self._ok and self._error:
                log.info("collector %s recovered", self._collector.name)
            self._ok = True
            self._error = None
        return self.snapshot()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._collector.interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"collect-{self.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def snapshot(self) -> Snapshot:
        with self._lock:
            data = self._data
            updated_at = self._updated_at
        return Snapshot(
            name=self.name,
            data=data,
            ok=self._ok,
            updated_at=updated_at,
            last_attempt=self._last_attempt,
            error=self._error,
        )


@dataclass
class Dashboard:
    """Aggregate of all collector runners; the render loop reads from here."""

    runners: dict[str, CollectorRunner] = field(default_factory=dict)

    def add(self, collector: Collector) -> CollectorRunner:
        runner = CollectorRunner(collector)
        self.runners[runner.name] = runner
        return runner

    def start_all(self) -> None:
        for r in self.runners.values():
            r.start()

    def stop_all(self) -> None:
        for r in self.runners.values():
            r.stop()

    def snapshots(self) -> dict[str, Snapshot]:
        return {name: r.snapshot() for name, r in self.runners.items()}
