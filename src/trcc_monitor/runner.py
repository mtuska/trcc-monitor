"""The run loop: collect → render → push, until signalled to stop.

Designed to run as a long-lived systemd user service:

* Collectors run in their own threads (see :mod:`.collectors.base`); the loop
  just samples their latest snapshots each tick.
* The frame is re-rendered every ``intervals.render`` seconds but only pushed
  to the sink when it actually changed — the trccd keepalive holds the panel
  between real updates, so this keeps CPU near idle.
* The sink is reconnected with capped backoff if the daemon isn't up yet or
  drops (device unplug, suspend/resume, daemon restart). A sink outage never
  exits the service.
* SIGTERM/SIGINT stop the loop cleanly so ``systemctl --user stop`` is graceful.
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from .app import build_dashboard, link_resets
from .config import Config
from .render.frame import DESIGN_H, DESIGN_W, render_dashboard
from .sinks import SinkError, build_sink

log = logging.getLogger(__name__)

_RECONNECT_MIN = 2.0
_RECONNECT_MAX = 30.0


def run_loop(config: Config) -> int:
    stop = threading.Event()

    def _handle(signum, _frame):
        log.info("received signal %s — stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    dash, collectors = build_dashboard(config)
    dash.start_all()
    log.info("started collectors: %s", ", ".join(dash.runners))

    sink = build_sink(config)
    connected = False
    reconnect_delay = _RECONNECT_MIN
    next_reconnect = 0.0
    last_hash: int | None = None
    render_interval = max(0.1, config.intervals.render)

    try:
        while not stop.is_set():
            now = time.monotonic()

            # (Re)connect the sink if needed, with capped backoff.
            if not connected and now >= next_reconnect:
                try:
                    sink.connect()
                    connected = True
                    reconnect_delay = _RECONNECT_MIN
                    last_hash = None  # force a push on fresh connection
                    log.info("sink connected (resolution=%s)", sink.resolution())
                except SinkError as e:
                    next_reconnect = now + reconnect_delay
                    reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX)
                    log.warning("sink connect failed: %s (retry in %.0fs)",
                                e, reconnect_delay)

            if connected:
                link_resets(collectors)
                snaps = dash.snapshots()
                size = sink.resolution() or (DESIGN_W, DESIGN_H)
                img = render_dashboard(snaps, size=size)
                frame_hash = hash(img.tobytes())
                if frame_hash != last_hash:
                    try:
                        sink.push(img)
                        last_hash = frame_hash
                    except SinkError as e:
                        log.warning("sink push failed: %s — reconnecting", e)
                        connected = False
                        next_reconnect = time.monotonic() + reconnect_delay

            # Sleep to the next wall-clock boundary so the on-screen clock ticks
            # crisply (no drift or skipped/doubled seconds) instead of sleeping a
            # flat interval that slowly slides off the second.
            slack = render_interval - (time.time() % render_interval)
            if slack < 0.02:
                slack += render_interval
            stop.wait(slack)
    finally:
        log.info("shutting down")
        dash.stop_all()
        try:
            sink.close()
        except Exception:
            log.debug("sink close failed", exc_info=True)
    return 0
