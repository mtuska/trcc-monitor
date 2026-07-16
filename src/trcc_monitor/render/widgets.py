"""Reusable drawing primitives for the dashboard.

All helpers take a :class:`PIL.ImageDraw.ImageDraw` and draw within an (x, y,
w, h) box. Coordinates are pixels. Nothing here knows about collectors — these
are pure visual building blocks composed by :mod:`.frame`.
"""
from __future__ import annotations

import math

from PIL import ImageDraw

from . import theme


def text(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    s: str,
    *,
    weight: str = "regular",
    size: int = 20,
    fill=theme.TEXT,
    anchor: str = "la",
):
    d.text(xy, s, font=theme.font(weight, size), fill=fill, anchor=anchor)


def text_width(s: str, weight: str, size: int) -> int:
    return int(theme.font(weight, size).getlength(s))


def panel(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 12,
    fill=theme.PANEL,
    outline=theme.PANEL_EDGE,
):
    x, y, w, h = box
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline)


def progress_bar(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    frac: float,
    *,
    color=theme.ACCENT_BLUE,
    track=theme.TRACK,
    radius: int | None = None,
):
    """Horizontal fill bar. ``frac`` clamped to [0, 1]."""
    x, y, w, h = box
    frac = max(0.0, min(1.0, frac))
    r = radius if radius is not None else h // 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=track)
    if frac > 0:
        fill_w = max(int(h), int(w * frac))  # keep the rounded cap visible
        d.rounded_rectangle([x, y, x + fill_w, y + h], radius=r, fill=color)


def sparkline(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    values: list[float],
    *,
    color=theme.ACCENT_BLUE,
    fill=True,
    baseline: float = 0.0,
):
    """Filled line chart scaled to its own min/max."""
    x, y, w, h = box
    if not values:
        return
    lo = min(min(values), baseline)
    hi = max(max(values), baseline)
    span = (hi - lo) or 1.0
    n = len(values)
    step = w / max(1, n - 1) if n > 1 else w

    def pt(i, v):
        px = x + i * step
        py = y + h - (v - lo) / span * h
        return (px, py)

    points = [pt(i, v) for i, v in enumerate(values)]
    if fill and len(points) >= 2:
        poly = points + [(x + w, y + h), (x, y + h)]
        d.polygon(poly, fill=_dim(color, 0.28))
    if len(points) >= 2:
        d.line(points, fill=color, width=2, joint="curve")
    else:
        d.ellipse([points[0][0] - 1, points[0][1] - 1,
                   points[0][0] + 1, points[0][1] + 1], fill=color)


def dual_area(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    series_a: list[float],
    series_b: list[float],
    *,
    color_a=theme.ACCENT_BLUE,
    color_b=theme.ACCENT_ORANGE,
):
    """Two overlaid area sparklines sharing a common scale (e.g. up/down rates)."""
    x, y, w, h = box
    all_vals = (series_a or []) + (series_b or [])
    hi = max(all_vals) if all_vals else 1.0
    hi = hi or 1.0

    def points(series):
        if not series:
            return []
        n = len(series)
        step = w / max(1, n - 1) if n > 1 else w
        return [(x + i * step, y + h - (v / hi) * h) for i, v in enumerate(series)]

    pa, pb = points(series_a), points(series_b)
    # Fills first (both faint so overlap stays readable)...
    for pts, color in ((pa, color_a), (pb, color_b)):
        if len(pts) >= 2:
            d.polygon(pts + [(x + w, y + h), (x, y + h)], fill=_dim(color, 0.10))
    # ...then both lines on top, so neither is buried under the other's fill.
    for pts, color in ((pa, color_a), (pb, color_b)):
        if len(pts) >= 2:
            d.line(pts, fill=color, width=2, joint="curve")


def bar_sparkline(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    values: list[float],
    *,
    color=theme.ACCENT_BLUE,
    gap: int = 3,
    highlight: int | None = -1,
):
    """Small column chart (the widget's 7-day style).

    ``highlight`` is the index drawn at full strength (default last = today);
    other bars are dimmed, matching the KDE widget's today emphasis.
    """
    x, y, w, h = box
    if not values:
        return
    hi = max(values) or 1.0
    n = len(values)
    hi_idx = highlight % n if highlight is not None else None
    dim = _dim(color, 0.5)
    bw = max(2, (w - gap * (n - 1)) / n)
    for i, v in enumerate(values):
        bh = max(1, int(h * (v / hi)))
        bx = x + i * (bw + gap)
        c = color if i == hi_idx else dim
        d.rectangle([bx, y + h - bh, bx + bw, y + h], fill=c)


def ring(
    d: ImageDraw.ImageDraw,
    center: tuple[int, int],
    radius: int,
    frac: float,
    *,
    color=theme.ACCENT_BLUE,
    track=theme.TRACK,
    width: int = 12,
):
    """Circular gauge (like the CPU/memory donuts in the KDE dashboard)."""
    cx, cy = center
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    frac = max(0.0, min(1.0, frac))
    d.arc(box, start=0, end=360, fill=track, width=width)
    if frac > 0:
        d.arc(box, start=-90, end=-90 + int(360 * frac), fill=color, width=width)


def thermometer(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    temp: float,
    *,
    scale: tuple[float, float],
    advised: tuple[float, float],
    color: tuple[int, int, int],
):
    """A vertical thermometer inside ``box`` (x, y, w, h): a glass tube with a
    bulb reservoir, mercury filled to ``temp`` and tinted ``color``, colored
    advised-min/max ticks with labels, and the current reading above the tube.
    """
    x, y, _wd, ht = box
    lo, hi = scale
    amin, amax = advised

    tube_w = 11
    bulb_r = 9
    tube_x = x + 3
    cx = tube_x + tube_w / 2
    tube_top = y + 18
    bulb_cy = y + ht - bulb_r - 1
    tube_bottom = bulb_cy

    def level_y(t: float) -> float:
        f = (t - lo) / (hi - lo) if hi > lo else 0.0
        f = max(0.0, min(1.0, f))
        return tube_bottom - f * (tube_bottom - tube_top)

    # Glass (empty): tube + bulb in the track color.
    d.rounded_rectangle([tube_x, tube_top, tube_x + tube_w, tube_bottom],
                        radius=tube_w / 2, fill=theme.TRACK)
    d.ellipse([cx - bulb_r, bulb_cy - bulb_r, cx + bulb_r, bulb_cy + bulb_r],
              fill=theme.TRACK)

    # Mercury: the bulb is always full; a column rises to the current temp.
    d.ellipse([cx - bulb_r + 2, bulb_cy - bulb_r + 2,
               cx + bulb_r - 2, bulb_cy + bulb_r - 2], fill=color)
    top_y = level_y(temp)
    mw = tube_w - 4
    if top_y < tube_bottom - 1:
        d.rounded_rectangle([cx - mw / 2, top_y, cx + mw / 2, tube_bottom],
                            radius=mw / 2, fill=color)

    # Advised min/max ticks + labels to the right of the tube.
    tick_x0 = tube_x + tube_w + 2
    tick_x1 = tick_x0 + 6
    for val, tcol in ((amin, theme.ACCENT_GREEN), (amax, theme.ACCENT_RED)):
        ty = level_y(val)
        d.line([tick_x0, ty, tick_x1, ty], fill=tcol, width=2)
        text(d, (tick_x1 + 3, ty), f"{val:.0f}", weight="medium", size=10,
             fill=tcol, anchor="lm")

    # Current reading above the tube, tinted like the mercury.
    text(d, (tick_x1, y + 8), f"{temp:.0f}°", weight="bold", size=13,
         fill=color, anchor="mm")


def _flat_top_perimeter(box, radius):
    """Ordered points tracing a flat-top / rounded-bottom tab, clockwise from
    the top-centre (so progress reads like a clock hand from 12 o'clock)."""
    x, y, wd, ht = box
    left, right, top, bottom = x, x + wd, y, y + ht
    r = radius
    cxm = (left + right) / 2
    pts = [(cxm, top), (right, top), (right, bottom - r)]
    for a in range(0, 91, 6):                      # bottom-right corner
        rad = math.radians(a)
        pts.append((right - r + r * math.cos(rad), bottom - r + r * math.sin(rad)))
    pts.append((left + r, bottom))
    for a in range(90, 181, 6):                    # bottom-left corner
        rad = math.radians(a)
        pts.append((left + r + r * math.cos(rad), bottom - r + r * math.sin(rad)))
    pts.append((left, top))
    pts.append((cxm, top))                         # close back to the start
    return pts


def progress_border(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    frac: float,
    *,
    track=theme.PANEL_EDGE,
    color=theme.ACCENT_BLUE,
    width: int = 3,
):
    """Draw a flat-top/rounded-bottom outline where the stroke itself is a
    progress ring: a dim full-perimeter track plus a bright arc that grows
    ``frac`` of the way around, clockwise from top-centre."""
    pts = _flat_top_perimeter(box, radius)
    d.line(pts, fill=track, width=width, joint="curve")

    seg = [math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
           for i in range(1, len(pts))]
    total = sum(seg)
    target = total * max(0.0, min(1.0, frac))
    prog = [pts[0]]
    acc = 0.0
    for i in range(1, len(pts)):
        length = seg[i - 1]
        if acc + length <= target:
            prog.append(pts[i])
            acc += length
        else:
            t = (target - acc) / length if length > 0 else 0
            prog.append((pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t,
                         pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t))
            break
    if len(prog) >= 2:
        d.line(prog, fill=color, width=width, joint="curve")


def status_dot(
    d: ImageDraw.ImageDraw, center: tuple[int, int], color, radius: int = 7
):
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)


def _dim(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Blend a color toward the panel background for fills."""
    bg = theme.PANEL
    return tuple(int(c * factor + b * (1 - factor)) for c, b in zip(color, bg))
