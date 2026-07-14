"""Compose collector snapshots into a single dashboard frame.

Designed at 1920×462 (the Trofeo Vision's default LY render surface) but laid
out proportionally so the handshake-reported resolution — which may instead be
1280×480 or 1920×440 — still fills correctly. The renderer never assumes a
fixed size; :func:`render_dashboard` takes the size from its sink/caller.

Layout mirrors the user's desktop: a dense Claude card on the left (rate-limit
windows + today's usage + 7-day sparkline, packed like the KDE widget) and the
system metrics as compact tiles filling the ultrawide's remaining width.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

from ..collectors.base import Snapshot
from ..config import Config
from . import theme, widgets as w

DESIGN_W = 1920
DESIGN_H = 462

STALE_AFTER = {
    "limits": 15 * 60,
    "usage": 5 * 60,
    "sessions": 60,
    "status": 10 * 60,
    "system": 20,
}


def render_dashboard(
    snapshots: dict[str, Snapshot],
    size: tuple[int, int] = (DESIGN_W, DESIGN_H),
    now: float | None = None,
) -> Image.Image:
    now = now if now is not None else time.time()
    img = Image.new("RGB", (DESIGN_W, DESIGN_H), theme.BG)
    d = ImageDraw.Draw(img)

    M = 14
    GAP = 10
    CLOCK_H = 46
    claude_w = 720
    sys_x = M + claude_w + GAP
    sys_w = DESIGN_W - M - sys_x
    # The clock tab hangs flush from the very top (y=0); panels start below it.
    top = CLOCK_H + 8
    bottom = DESIGN_H - M
    height = bottom - top

    _draw_claude(d, snapshots, now, M, top, claude_w, height)
    _draw_system(d, snapshots, now, sys_x, top, sys_w, height, GAP)
    _draw_clock(d, snapshots, now, DESIGN_W // 2, CLOCK_H, M)

    if size != (DESIGN_W, DESIGN_H):
        img = img.resize(size, Image.LANCZOS)
    return img


# ── clock ──────────────────────────────────────────────────────────────
def _clock_tab(d, now, cx, band_h):
    """The flat-top clock tab with its 0→60s progress-ring border (no flanks)."""
    hhmm = time.strftime("%H:%M:%S", time.localtime(now))
    date = time.strftime("%a %d %b", time.localtime(now))
    time_w = w.text_width("00:00:00", "mono", 26)
    date_w = w.text_width(date, "regular", 14)
    pad = 24
    inner_gap = 18
    tab_w = pad + time_w + inner_gap + date_w + pad
    px = cx - tab_w // 2
    cyc = band_h // 2
    r = 16
    d.rounded_rectangle([px, 0, px + tab_w, band_h], radius=r,
                        corners=(False, False, True, True), fill=theme.PANEL_INNER)
    frac = (now % 60) / 60.0
    w.progress_border(d, (px + 2, 2, tab_w - 4, band_h - 2), r - 2, frac,
                      track=theme.PANEL_EDGE, color=theme.ACCENT_BLUE, width=3)
    w.text(d, (px + pad, cyc), hhmm, weight="mono", size=26, fill=theme.TEXT,
           anchor="lm")
    w.text(d, (px + pad + time_w + inner_gap, cyc), date, weight="regular", size=14,
           fill=theme.TEXT_DIM, anchor="lm")
    return px, tab_w


# ── clock ──────────────────────────────────────────────────────────────
def _draw_clock(d, snaps, now, cx, band_h, margin):
    """Landscape top band: the clock tab (via _clock_tab) plus the system load
    average on the left flank and a UTC companion clock on the right."""
    cyc = band_h // 2
    px, tab_w = _clock_tab(d, now, cx, band_h)

    # Left flank: system load average (1 / 5 / 15 min).
    load = _d(snaps.get("system")).get("load_avg")
    if load:
        lx = margin + 6
        w.text(d, (lx, cyc), "load", weight="medium", size=13,
               fill=theme.TEXT_FAINT, anchor="lm")
        w.text(d, (lx + w.text_width("load", "medium", 13) + 12, cyc),
               f"{load[0]:.2f}  ·  {load[1]:.2f}  ·  {load[2]:.2f}",
               weight="mono", size=14, fill=theme.TEXT_DIM, anchor="lm")

    # UTC companion clock (ISO 8601), just right of the tab.
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    w.text(d, (px + tab_w + 18, cyc), utc, weight="mono", size=13,
           fill=theme.TEXT_FAINT, anchor="lm")


# ── staleness ──────────────────────────────────────────────────────────
def _stale(snap: Snapshot | None, now: float) -> bool:
    if snap is None or snap.data is None:
        return True
    return snap.age(now) > STALE_AFTER.get(snap.name, 300)


def _stale_tag(d, snap, now, x, y):
    if snap is None:
        return
    if _stale(snap, now):
        age = snap.age(now)
        label = "no data" if age == float("inf") else f"stale {int(age // 60)}m"
        color = theme.ACCENT_RED
    elif not snap.ok:
        label = "refresh failed"
        color = theme.ACCENT_YELLOW
    else:
        return
    w.text(d, (x, y), label, weight="medium", size=13, fill=color, anchor="ra")
    w.status_dot(d, (x - w.text_width(label, "medium", 13) - 9, y + 8), color, radius=4)


def _d(snap):
    return snap.data if snap and snap.data else {}


# ── Claude card ────────────────────────────────────────────────────────
def _draw_claude(d, snaps, now, x, y, width, height):
    w.panel(d, (x, y, width, height), radius=12, outline=None)
    pad = 20
    ix = x + pad
    iw = width - 2 * pad

    limits = snaps.get("limits")
    usage = snaps.get("usage")
    sessions = snaps.get("sessions")
    status = snaps.get("status")
    ld, ud, sd, std = _d(limits), _d(usage), _d(sessions), _d(status)

    # Title + refresh/staleness.
    cy = y + 16
    w.text(d, (ix, cy), "CLAUDE", weight="bold", size=20, fill=theme.TEXT)
    plan = (ld.get("plan") or "").upper()
    if plan:
        w.text(d, (ix + w.text_width("CLAUDE", "bold", 20) + 12, cy + 4), plan,
               weight="bold", size=14, fill=theme.ACCENT_ORANGE)
    _stale_tag(d, limits, now, x + width - pad, cy + 2)

    # Service status line.
    cy += 30
    indicator = std.get("indicator") or "none"
    desc = std.get("description") or "—"
    w.status_dot(d, (ix + 5, cy + 8), theme.STATUS_COLORS.get(indicator, theme.TEXT_DIM),
                 radius=5)
    w.text(d, (ix + 16, cy), desc, weight="regular", size=14, fill=theme.TEXT_DIM)
    # Agents working, right-aligned.
    agents = sd.get("agents", 0)
    subs = sd.get("subagents", 0)
    if agents or subs:
        bits = [f"{agents} agent{'s' if agents != 1 else ''}"]
        if subs:
            bits.append(f"{subs} sub")
        w.text(d, (x + width - pad, cy), " · ".join(bits) + " working",
               weight="regular", size=13, fill=theme.TEXT_FAINT, anchor="ra")

    # Rate-limit windows.
    rate = ud.get("rate_per_hour", 0)
    wy = cy + 32
    _limit_window(d, "5-hour", ld.get("h5", {}), ud.get("window_5h_tokens", 0),
                  rate, now, ix, wy, iw)
    wy += 74
    _limit_window(d, "7-day", ld.get("d7", {}), ud.get("window_7d_tokens", 0),
                  rate, now, ix, wy, iw)

    # Usage credits (overage).
    wy += 70
    overage = (ld.get("overage_status") or "").lower()
    credit_txt, credit_col = {
        "allowed": ("available", theme.ACCENT_GREEN),
        "rejected": ("disabled", theme.TEXT_DIM),
    }.get(overage, ("—", theme.TEXT_FAINT))
    w.text(d, (ix, wy), "Usage credits", weight="regular", size=13, fill=theme.TEXT_FAINT)
    w.text(d, (ix + w.text_width("Usage credits", "regular", 13) + 8, wy), credit_txt,
           weight="medium", size=13, fill=credit_col)

    # Divider.
    wy += 26
    d.line([(ix, wy), (ix + iw, wy)], fill=theme.PANEL_EDGE, width=1)

    # Today.
    wy += 14
    _today_block(d, usage, now, ix, wy, iw)

    # Footer: incidents/maintenance (left, when present) + plan · updated (right).
    fy = y + height - 24
    _claude_footer(d, ld, std, fy, ix, iw)


def _claude_footer(d, ld, std, fy, ix, iw):
    # Degraded-state storytelling: surface the first incident or maintenance.
    incidents = std.get("incidents") or []
    maints = std.get("maintenances") or []
    if incidents:
        it = incidents[0]
        txt = "• " + (it.get("name") or "Incident")
        col = theme.STATUS_COLORS.get((it.get("impact") or "").lower(), theme.ACCENT_RED)
    elif maints:
        txt = "• " + (maints[0].get("name") or "Scheduled maintenance")
        col = theme.ACCENT_YELLOW
    else:
        txt, col = None, None
    if txt:
        w.text(d, (ix, fy), _elide(txt, int(iw * 0.6), "regular", 12), weight="regular",
               size=12, fill=col)

    # Updated HH:MM (right).
    updated = _to_float(ld.get("updated_at"))
    if updated > 0:
        w.text(d, (ix + iw, fy),
               "updated " + time.strftime("%H:%M", time.localtime(updated)),
               weight="regular", size=12, fill=theme.TEXT_FAINT, anchor="ra")


def _elide(s: str, max_px: int, weight: str, size: int) -> str:
    if w.text_width(s, weight, size) <= max_px:
        return s
    while s and w.text_width(s + "…", weight, size) > max_px:
        s = s[:-1]
    return s + "…"


def _limit_window(d, label, win, used, rate, now, x, y, width):
    util = float(win.get("utilization", 0.0) or 0.0)
    wstatus = (win.get("status") or "").lower()
    reset_in = win.get("reset_in")
    limited = wstatus in ("rejected", "blocked", "limited") or util >= 1.0

    # Label + percentage on one line (+ LIMITED tag when capped).
    w.text(d, (x, y), label, weight="medium", size=14, fill=theme.TEXT_DIM)
    if limited:
        w.text(d, (x + w.text_width(label, "medium", 14) + 10, y + 2), "LIMITED",
               weight="bold", size=11, fill=theme.ACCENT_RED)
    pct_col = theme.ACCENT_RED if limited else theme.TEXT
    w.text(d, (x + width, y - 2), f"{util * 100:.0f}%", weight="bold", size=19,
           fill=pct_col, anchor="ra")

    # Thin bar — Claude terracotta / warm / red, per the widget.
    by = y + 24
    w.progress_bar(d, (x, by, width, 7), util,
                   color=theme.limit_bar_color(wstatus, util))

    # Sub-line: reset + token estimate.
    sy = by + 13
    if reset_in:
        w.text(d, (x, sy), f"resets {reset_in}", weight="regular", size=12,
               fill=theme.TEXT_FAINT)
    ceiling, eta = theme.limit_estimate(used, util, rate)
    if ceiling:
        est = f"~{theme.human_tokens(used)} / ~{theme.human_tokens(ceiling)} tok"
        w.text(d, (x + width, sy), est, weight="regular", size=12,
               fill=theme.TEXT_DIM, anchor="ra")

    # ETA line. "(resets first)" flags the common case where the window resets
    # before you'd hit the cap; when the cap comes first it's urgent (warm).
    ey = sy + 16
    if limited:
        w.text(d, (x, ey), "limit reached", weight="medium", size=12,
               fill=theme.ACCENT_RED)
    elif eta is not None and eta > 0:
        reset_ts = _to_float(win.get("reset_ts"))
        hours_to_reset = (reset_ts - now) / 3600.0 if reset_ts > 0 else 0.0
        eta_before_reset = 0 < eta < hours_to_reset if hours_to_reset > 0 else False
        tag = "full in " + theme.fmt_duration(eta)
        if not eta_before_reset:
            tag += "  (resets first)"
        w.text(d, (x, ey), tag, weight="regular", size=12,
               fill=theme.WARN_COLOR if eta_before_reset else theme.TEXT_FAINT)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _today_block(d, usage, now, x, y, width):
    ud = _d(usage)
    today = ud.get("today", {})
    total = today.get("total", 0)
    cost = today.get("cost", 0.0)
    cache_hit = today.get("cache_hit", 0.0)

    # Headline: Today  <tokens>  ~$cost      <cache%>
    w.text(d, (x, y), "Today", weight="medium", size=14, fill=theme.TEXT_DIM)
    hx = x + w.text_width("Today", "medium", 14) + 12
    tok = theme.human_tokens(total)
    w.text(d, (hx, y - 3), tok, weight="bold", size=20, fill=theme.TEXT)
    hx += w.text_width(tok, "bold", 20) + 10
    w.text(d, (hx, y), f"~${cost:,.2f}", weight="medium", size=15,
           fill=theme.ACCENT_GREEN)
    w.text(d, (x + width, y), f"{cache_hit * 100:.0f}% cached", weight="regular",
           size=12, fill=theme.TEXT_DIM, anchor="ra")
    _stale_tag(d, usage, now, x + width, y + 20)

    # Per-model split as text (dense, like the widget).
    by_model = ud.get("by_model", {}) or {}
    mtotal = sum(by_model.values()) or 1
    parts = [f"{n} {v / mtotal * 100:.0f}%"
             for n, v in sorted(by_model.items(), key=lambda kv: -kv[1]) if v > 0]
    my = y + 28
    if parts:
        w.text(d, (x, my), "  ·  ".join(parts), weight="regular", size=13,
               fill=theme.TEXT_DIM)

    # 7-day sparkline (bars), labelled.
    daily = ud.get("daily", []) or []
    sy = my + 24
    w.text(d, (x, sy), "7-day", weight="regular", size=12, fill=theme.TEXT_FAINT)
    w.bar_sparkline(d, (x, sy + 16, width, 34), daily, color=theme.ACCENT_BLUE)


# ── System panel ───────────────────────────────────────────────────────
def _draw_system(d, snaps, now, x, y, width, height, gap):
    w.panel(d, (x, y, width, height), radius=12, outline=None)
    pad = 20
    ix = x + pad
    iw = width - 2 * pad
    sys_snap = snaps.get("system")
    sysd = _d(sys_snap)
    gpud = _d(snaps.get("gpu"))
    gpu_ok = bool(gpud.get("available"))

    w.text(d, (ix, y + 16), "SYSTEM", weight="bold", size=13, fill=theme.TEXT_DIM)
    _stale_tag(d, sys_snap, now, ix + iw, y + 16)

    # Two inner cards: CPU+MEM and GPU+VRAM (each titled with the chip name).
    card_gap = 12
    card_y = y + 42
    card_h = 176
    if gpu_ok:
        card_w = (iw - card_gap) // 2
        _inner_card(d, (ix, card_y, card_w, card_h),
                    _short_cpu(sysd.get("cpu_name", "CPU")),
                    [_cpu_ring(sysd), _mem_ring(sysd)])
        _inner_card(d, (ix + card_w + card_gap, card_y, iw - card_w - card_gap, card_h),
                    _short_gpu(gpud.get("name", "GPU")),
                    [_gpu_ring(gpud), _vram_ring(gpud)])
    else:
        _inner_card(d, (ix, card_y, iw, card_h),
                    _short_cpu(sysd.get("cpu_name", "CPU")),
                    [_cpu_ring(sysd), _mem_ring(sysd)])

    # Bottom row: disk ring (left) + network graph (right).
    by = card_y + card_h + 16
    bh = y + height - pad - by
    disk_w = 220
    _disk_gauge(d, sysd, ix, by, disk_w, bh)
    _net_row(d, sysd, ix + disk_w + 24, by, iw - disk_w - 24, bh)


def _inner_card(d, box, title, rings):
    x, y, cw, ch = box
    w.panel(d, box, radius=10, fill=theme.PANEL_INNER, outline=None)
    w.text(d, (x + 16, y + 12), _elide(title, cw - 32, "medium", 13),
           weight="medium", size=13, fill=theme.TEXT_DIM)
    n = len(rings)
    col_w = cw / n
    r = 38
    label_y = y + 42
    cy = label_y + 14 + r
    for i, (val, label, color, sub) in enumerate(rings):
        cx = int(x + col_w * (i + 0.5))
        w.text(d, (cx, label_y), label, weight="medium", size=12,
               fill=theme.TEXT_DIM, anchor="mm")
        w.ring(d, (cx, cy), r, val / 100.0, color=color, width=8)
        w.text(d, (cx, cy - 2), f"{val:.0f}%", weight="bold", size=20,
               fill=theme.TEXT, anchor="mm")
        if sub:
            w.text(d, (cx, cy + r + 14), sub, weight="regular", size=12,
                   fill=theme.TEXT_FAINT, anchor="mm")


def _short_gpu(name: str) -> str:
    """'NVIDIA GeForce RTX 4090' → 'RTX 4090'; keep AMD names short too."""
    for marker in ("RTX", "GTX", "Radeon", "Arc", "RX"):
        if marker in name:
            return name[name.index(marker):]
    return name


def _short_cpu(name: str) -> str:
    """'AMD Ryzen 9 7950X 16-Core Processor' → 'Ryzen 9 7950X'."""
    import re
    n = re.sub(r"\((R|TM)\)", "", name)
    n = re.sub(r"\b\d+-Core Processor\b", "", n)
    n = re.sub(r"\bCPU\b.*", "", n)          # drop "CPU @ 3.4GHz" tails
    n = re.sub(r"\bProcessor\b", "", n)
    n = n.replace("AMD ", "").replace("Intel ", "")
    return " ".join(n.split()) or name


def _cpu_ring(sysd):
    sub = []
    if sysd.get("cpu_temp"):
        sub.append(f"{sysd['cpu_temp']:.0f}°C")
    if sysd.get("cpu_cores"):
        sub.append(f"{sysd['cpu_cores']}c")
    return (float(sysd.get("cpu_percent", 0.0)), "CPU", theme.ACCENT_BLUE,
            " · ".join(sub))


def _gpu_ring(gpud):
    sub = []
    if gpud.get("temp"):
        sub.append(f"{gpud['temp']:.0f}°C")
    if gpud.get("power"):
        sub.append(f"{gpud['power']:.0f}W")
    return (float(gpud.get("usage_percent", 0.0)), "GPU", theme.ACCENT_PURPLE,
            " · ".join(sub))


def _mem_ring(sysd):
    return (float(sysd.get("mem_percent", 0.0)), "MEM", theme.ACCENT_ORANGE,
            f"{theme.human_bytes(sysd.get('mem_used', 0))} / "
            f"{theme.human_bytes(sysd.get('mem_total', 0))}")


def _vram_ring(gpud):
    return (float(gpud.get("vram_percent", 0.0)), "VRAM", theme.ACCENT_GREEN,
            f"{theme.human_bytes(gpud.get('vram_used', 0))} / "
            f"{theme.human_bytes(gpud.get('vram_total', 0))}")


def _disk_gauge(d, sysd, x, y, width, height):
    pct = float(sysd.get("disk_percent", 0.0))
    cx = x + width // 2
    # Cap the radius so it matches the inner-card rings rather than ballooning
    # to fill the taller bottom row.
    r = min(width // 2 - 24, (height - 56) // 2, 44)
    cy = y + (height - r) // 2
    w.text(d, (cx, cy - r - 18), "DISK", weight="medium", size=12,
           fill=theme.TEXT_DIM, anchor="mm")
    w.ring(d, (cx, cy), r, pct / 100.0, color=theme.util_color(pct / 100.0), width=8)
    w.text(d, (cx, cy - 2), f"{pct:.0f}%", weight="bold", size=20,
           fill=theme.TEXT, anchor="mm")
    free = sysd.get("disk_free", 0)
    w.text(d, (cx, cy + r + 14), f"{theme.human_bytes(free)} free",
           weight="regular", size=12, fill=theme.TEXT_FAINT, anchor="mm")


def _net_row(d, sysd, x, y, width, height):
    up = sysd.get("net_up_history", []) or []
    down = sysd.get("net_down_history", []) or []
    up_rate = sysd.get("net_up_rate", 0.0)
    down_rate = sysd.get("net_down_rate", 0.0)

    w.text(d, (x, y + 6), "Network", weight="medium", size=13, fill=theme.TEXT_DIM)
    # Legend with live rates (top-right).
    dn_label = f"Dn {theme.human_rate(down_rate)}"
    up_label = f"Up {theme.human_rate(up_rate)}"
    rx = x + width
    w.text(d, (rx, y + 6), dn_label, weight="regular", size=12,
           fill=theme.TEXT_DIM, anchor="ra")
    dn_x = rx - w.text_width(dn_label, "regular", 12) - 9
    w.status_dot(d, (dn_x, y + 14), theme.ACCENT_BLUE, radius=4)
    up_right = dn_x - 20
    w.text(d, (up_right, y + 6), up_label, weight="regular", size=12,
           fill=theme.TEXT_DIM, anchor="ra")
    up_dot = up_right - w.text_width(up_label, "regular", 12) - 9
    w.status_dot(d, (up_dot, y + 14), theme.ACCENT_ORANGE, radius=4)

    gy = y + 28
    w.dual_area(d, (x, gy, width, y + height - gy), down, up,
                color_a=theme.ACCENT_BLUE, color_b=theme.ACCENT_ORANGE)


# ── Preview entry point ────────────────────────────────────────────────
def render_preview(
    config: Config, mock: bool = False, out_path: str | None = None
) -> str:
    if mock:
        from .mock import snapshots as mock_snaps
        snaps = mock_snaps()
    else:
        from ..app import build_dashboard, link_resets
        dash, collectors = build_dashboard(config)
        # Poll limits first so usage can align its windows, then everything else.
        order = sorted(dash.runners, key=lambda n: 0 if n == "limits" else 1)
        for name in order:
            if name != "limits":
                link_resets(collectors)
            dash.runners[name].poll_once()
        snaps = dash.snapshots()

    img = render_dashboard(snaps)
    path = Path(out_path).expanduser() if out_path else Path.cwd() / "preview.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return str(path)
