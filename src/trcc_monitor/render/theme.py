"""Colors, fonts, and formatting helpers for the dashboard.

Dark theme tuned for an LCD mounted inside a case window: near-black background,
high-contrast text, and the orange/blue accents from the original KDE widgets.
"""
from __future__ import annotations

import functools
from importlib import resources

from PIL import ImageFont

# ── Palette (RGB) ──────────────────────────────────────────────────────
BG = (12, 14, 18)
PANEL = (20, 23, 29)
PANEL_INNER = (28, 32, 40)     # nested card inside a panel (a touch lighter)
PANEL_EDGE = (36, 40, 48)
TEXT = (232, 236, 242)
TEXT_DIM = (150, 158, 170)
TEXT_FAINT = (96, 104, 116)

# Claude brand colors, carried over from the KDE widget (utils.js) — these tell
# the rate-limit "story": terracotta while healthy, warm as you approach the
# cap, red when limited.
CLAUDE_COLOR = (218, 119, 86)      # #DA7756 — normal limit bar
WARN_COLOR = (232, 168, 124)       # #E8A87C — util > 0.85, and "major" severity
WARN_THRESHOLD = 0.85

ACCENT_ORANGE = (232, 168, 124)    # warm accent (= WARN_COLOR)
ACCENT_BLUE = (94, 165, 235)       # cool accent / system rings
ACCENT_GREEN = (110, 200, 130)     # OK status / healthy
ACCENT_YELLOW = (235, 200, 90)     # warning
ACCENT_RED = (232, 96, 96)         # critical / limited
ACCENT_PURPLE = (170, 150, 235)    # GPU accent
TRACK = (40, 44, 52)               # empty portion of a bar

# Service-status indicator → color (mirrors utils.js severityColor).
STATUS_COLORS = {
    "none": ACCENT_GREEN,
    "minor": ACCENT_YELLOW,
    "major": WARN_COLOR,
    "critical": ACCENT_RED,
}


def limit_bar_color(status: str, util: float) -> tuple[int, int, int]:
    """Color a rate-limit bar exactly as the KDE widget does."""
    if (status or "").lower() in ("limited", "blocked", "rejected"):
        return ACCENT_RED
    return WARN_COLOR if util > WARN_THRESHOLD else CLAUDE_COLOR


def util_color(util: float) -> tuple[int, int, int]:
    """Health ramp for system bars (disk, etc.): green→yellow→warm→red."""
    if util >= 1.0:
        return ACCENT_RED
    if util >= 0.9:
        return WARN_COLOR
    if util >= 0.75:
        return ACCENT_YELLOW
    return ACCENT_GREEN


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


# Advised operating envelope per chip, in °C: (scale_min, scale_max) is the
# thermometer's drawn range; (advised_min, advised_max) are the marked ticks —
# roughly a healthy idle floor and the point where silicon starts to throttle.
# General guidance, not per-part datasheet values.
CPU_TEMP = {"scale": (30, 100), "advised": (45, 85)}
GPU_TEMP = {"scale": (30, 100), "advised": (45, 83)}


def temp_color(temp: float, advised_max: float) -> tuple[int, int, int]:
    """Smooth green→yellow→orange→red ramp keyed to a chip's advised max, so
    the same function reads correctly for a CPU (85°C) or a GPU (83°C)."""
    r = temp / advised_max if advised_max else 0.0
    stops = (
        (0.00, ACCENT_GREEN),
        (0.75, ACCENT_GREEN),
        (0.90, ACCENT_YELLOW),
        (1.00, ACCENT_ORANGE),
        (1.12, ACCENT_RED),
    )
    if r <= stops[0][0]:
        return stops[0][1]
    if r >= stops[-1][0]:
        return stops[-1][1]
    for (r0, c0), (r1, c1) in zip(stops, stops[1:]):
        if r <= r1:
            t = (r - r0) / (r1 - r0) if r1 > r0 else 0.0
            return _lerp(c0, c1, t)
    return stops[-1][1]


# ── Fonts ──────────────────────────────────────────────────────────────
_FONT_FILES = {
    "regular": "NotoSans-Regular.ttf",
    "medium": "NotoSans-Medium.ttf",
    "bold": "NotoSans-Bold.ttf",
    "mono": "NotoSansMono.ttf",
}


@functools.lru_cache(maxsize=64)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled font at the given pixel size (cached)."""
    fname = _FONT_FILES.get(weight, _FONT_FILES["regular"])
    with resources.as_file(
        resources.files("trcc_monitor.assets.fonts") / fname
    ) as path:
        return ImageFont.truetype(str(path), size)


# ── Number formatting ──────────────────────────────────────────────────
def human_tokens(n: float) -> str:
    """Compact token count: 1234 → '1.2K', 1_500_000 → '1.5M'."""
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


def human_bytes(n: float) -> str:
    """Bytes → KiB/MiB/GiB/TiB with one decimal."""
    n = float(n)
    for unit, div in (("TiB", 2**40), ("GiB", 2**30), ("MiB", 2**20), ("KiB", 2**10)):
        if abs(n) >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def human_rate(bytes_per_s: float) -> str:
    """Byte rate → e.g. '88.4 KiB/s'."""
    return human_bytes(bytes_per_s) + "/s"


def fmt_duration(hours: float) -> str:
    """Hours → compact '45m' / '4h 14m' / '1d 10h'."""
    if hours < 0:
        return "now"
    total_min = int(round(hours * 60))
    if total_min < 60:
        return f"{total_min}m"
    h = total_min // 60
    if h < 24:
        m = total_min % 60
        return f"{h}h {m}m" if m else f"{h}h"
    days = h // 24
    rem_h = h % 24
    return f"{days}d {rem_h}h" if rem_h else f"{days}d"


def limit_estimate(used: float, util: float, rate_per_hour: float):
    """Estimate a window's token ceiling and burn-rate ETA to full.

    ceiling = used / utilization (the widget's ``used ÷ util`` heuristic);
    eta_hours = remaining / rate. Returns (ceiling, eta_hours), either of which
    may be None when the inputs don't support the estimate.
    """
    ceiling = used / util if util and util > 0 else None
    eta = None
    if ceiling is not None and rate_per_hour and rate_per_hour > 0:
        eta = max(0.0, ceiling - used) / rate_per_hour
    return ceiling, eta
