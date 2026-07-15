"""Smoke tests for the renderer: it must never crash and must honor size."""
import time

from trcc_monitor.collectors.base import Snapshot
from trcc_monitor.render.frame import DESIGN_H, DESIGN_W, render_dashboard
from trcc_monitor.render.mock import snapshots as mock_snapshots


def test_mock_render_default_size():
    img = render_dashboard(mock_snapshots())
    assert img.size == (DESIGN_W, DESIGN_H)
    assert img.mode == "RGB"


def test_render_scales_to_device_resolutions():
    for size in [(1920, 462), (1920, 440), (1280, 480)]:
        img = render_dashboard(mock_snapshots(), size=size)
        assert img.size == size


def test_render_empty_snapshots():
    # No collectors reported yet — must render (with stale markers), not crash.
    img = render_dashboard({})
    assert img.size == (DESIGN_W, DESIGN_H)


def test_limits_stale_threshold_exceeds_poll_interval():
    # The stale marker must not fire between normal polls.
    from trcc_monitor.config import Intervals
    from trcc_monitor.render.frame import STALE_AFTER
    assert STALE_AFTER["limits"] > Intervals().limits


def test_reset_countdown_is_derived_from_timestamp_not_poll():
    # A snapshot whose poll-time `reset_in` string is stale/wrong must still
    # render a countdown computed live from the absolute reset_ts.
    now = time.time()
    win = {"utilization": 0.5, "status": "allowed",
           "reset_ts": str(int(now + 2 * 3600)), "reset_in": "WRONG"}
    from trcc_monitor.collectors.limits import fmt_reset
    assert fmt_reset(win["reset_ts"], now) == "2h"
    # ...and an hour later the same snapshot reads down to 1h, no re-poll.
    assert fmt_reset(win["reset_ts"], now + 3600) == "1h"


def test_render_degraded_snapshot():
    now = time.time()
    # limits failed (data=None, not ok) — should render the "no data" state.
    snaps = {
        "limits": Snapshot("limits", None, ok=False, updated_at=0,
                           last_attempt=now, error="boom"),
        "system": mock_snapshots()["system"],
    }
    img = render_dashboard(snaps, now=now)
    assert img.size == (DESIGN_W, DESIGN_H)
