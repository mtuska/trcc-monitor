# trcc-monitor — Roadmap

Headless dashboard for the **Thermalright Trofeo Vision 9.16" LCD** (1920×480 panel), replacing the
KDE Plasma desktop widgets — primarily the Claude usage widget — with an always-on hardware display,
driven by a **systemd user service**. No GUI, no desktop dependency.

## Source material

| Repo | What we take from it |
|---|---|
| `~/git/claude-kde-usage-widget` | The Claude data-collection logic (`contents/code/fetch_limits.sh`, `fetch_usage.sh`, `fetch_sessions.sh`, `fetch_status.sh`) — already mostly Python heredocs, ready to port. The QML UI is discarded. |
| `~/git/thermalright-trcc-linux` | The device layer. Its daemon (`trccd`) owns the USB device; we feed it rendered frames over its REST API or Unix-socket IPC. We do **not** use its GUI or its built-in theme/metric system. |

## Hardware facts (from trcc-linux source)

- Trofeo Vision 9.16 = **LY-series bulk USB device**, VID:PID `0416:5408` (LY) or `0416:5409` (LY1)
  — `src/trcc/core/registry.py`, protocol in `src/trcc/adapters/device/ly_lcd.py`.
- Frames on the wire are **JPEG** (`FBL 192` profile: `jpeg=True, rotate=True, widescreen=True`,
  `src/trcc/core/protocol.py:114`). Marketing says 1920×480; the protocol's render surface is
  **1920×462** by default, and the handshake PM byte can instead select 1280×480 or 1920×440
  (`_FBL_192_BY_PM`). **Never hardcode the resolution — read it from the daemon after connect.**
- The firmware reverts to its boot logo if it doesn't receive a frame every ~2–3 s. trccd's
  `DeviceSender` (`src/trcc/services/device_sender.py`) handles this with a 150 ms keepalive resend
  of the last frame — a strong reason to let trccd own the device rather than talking USB ourselves.
- Non-root USB access needs the udev rules trcc-linux installs (`trcc system setup`,
  `packaging/udev/99-trcc-lcd.rules`), plus its SELinux module on Fedora/Bazzite.
- ⚠️ The display is not yet connected (`lsusb` shows no `0416:5408/5409`) — everything below that
  touches real hardware is blocked until it's installed. Development proceeds against a PNG
  preview sink regardless.

## Architecture

```
┌────────────────────────── trcc-monitor (our new code, Python) ──────────────────────────┐
│  Collectors (async, per-interval, cached)          Renderer            Sink             │
│  ├─ claude.limits   (API probe → ratelimit hdrs)   Pillow, 1920×462    ├─ trccd REST/IPC│
│  ├─ claude.usage    (~/.claude transcripts)   ──►  dark theme,    ──►  ├─ PNG file      │
│  ├─ claude.sessions (transcript mtimes)            layout regions      │  (dev preview) │
│  ├─ claude.status   (status.claude.com)                                └─ (stretch:     │
│  └─ system          (psutil: cpu/mem/disk/net)                            direct LY)    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                              │ POST /devices/{key}/display/send-image
                                              ▼
                    trccd daemon (trcc-linux, systemd user unit, QT_QPA_PLATFORM=offscreen)
                                              │ LY bulk protocol, JPEG, keepalive
                                              ▼
                                   Trofeo Vision 9.16 LCD
```

**Why feed trccd instead of driving USB directly:** trccd already handles handshake, resolution
discovery, the 150 ms keepalive, hotplug (pyudev), suspend/resume recovery, and udev/SELinux setup.
Its REST endpoint `POST /devices/{key}/display/send-image` (`src/trcc/ui/api/display.py`) accepts a
full image and runs it through the correct rotate/encode pipeline for the device. We render the
entire frame ourselves, so we deliberately ignore trcc-linux's theme/overlay/metric system (its
`metric` overlay elements can only read its own sensor keys — no external-data hook; see
`services/overlay.py`).

**Sink abstraction:** one small interface (`push_frame(image) / resolution() / close()`) with three
implementations — `TrccdSink` (REST, fallback IPC `SendImage` on the Unix socket
`$XDG_RUNTIME_DIR/trcc.sock`), `PngSink` (writes `/tmp/.../preview.png` for development without
hardware), and later, optionally, a standalone `LySink` (Phase 7). Everything above the sink is
hardware-agnostic.

## What goes on the screen

The 1920×462 ultrawide splits naturally into 3–4 columns. From the current desktop (Claude widget
README + screenshot), in priority order:

**Claude (primary, ~2/3 of the width):**
- 5-hour and 7-day windows: usage bar, %, reset countdown, token estimate (`~94.0M / ~626.5M`),
  "full in ~Xh" burn-rate ETA
- Service status dot + incident text ("All Systems Operational")
- Active agents / sub-agents working count
- Today: tokens, est. cost, cache-hit %, per-model split (Fable/Opus/Other)
- 7-day sparkline
- Usage-credits (overage) state
- Staleness indicator (last successful probe age) — a headless display **must** show when its data
  is stale, since nobody sees error logs

**System (secondary, right column):** CPU %, memory used/total + %, disk used/free + %, network
up/down rate, disk read/write rate. Small history graphs for net/disk like the current widgets.
(Sound devices explicitly stay on the desktop.)

## Phases

### Phase 0 — Environment prep (partially blocked on hardware)
- Install `trcc-linux` (pip package) and run `sudo trcc system setup` (udev + SELinux). Note:
  Bazzite is an immutable distro — decide pip `--user` / pipx / distrobox; document the choice.
- Enable the shipped daemon unit: `systemctl --user enable --now trccd.service`
  (`packaging/systemd/trccd.service`, uses `QT_QPA_PLATFORM=offscreen`).
- When the display arrives: verify with `trcc detect` / `trcc status`, note the device key and the
  handshake-reported resolution, and confirm `trcc display test-lcd` paints it.

### Phase 1 — Project scaffold
- Python package `trcc_monitor` (pyproject, `uv` or hatch), runtime deps: `Pillow`, `psutil`,
  `httpx` (or stdlib urllib). **No Qt, no PySide6** in our process.
- Config file `~/.config/trcc-monitor/config.toml`: device key, poll intervals, enabled panels,
  API-probe interval (each probe costs one real 1-token API call — default 5 min like the widget),
  proxy mode, theme options.
- Console entry point `trcc-monitor` with `run` (foreground loop), `preview` (render one frame to
  PNG and exit), `check` (collectors dry-run, print JSON).

### Phase 2 — Port the collectors
Port each widget script to a collector class with its own interval, last-good-value cache, and
error/staleness state (never crash the loop on a failed poll):
- `LimitsCollector` ← `fetch_limits.sh`: OAuth token from `~/.claude/.credentials.json`, minimal
  Haiku probe, parse `anthropic-ratelimit-unified-*` headers. Keep the stale-token recovery trick
  (spawn `timeout 5 claude -p x` once, re-read token, retry).
- `UsageCollector` ← `fetch_usage.sh`: transcript scan → today's tokens/cost, per-model split,
  cache-hit %, daily sparkline, per-window token sums + ceiling/ETA estimates (reset timestamps fed
  from `LimitsCollector`).
- `SessionsCollector` ← `fetch_sessions.sh`: agents/sub-agents via transcript mtime freshness.
- `StatusCollector` ← `fetch_status.sh`: `status.claude.com/api/v2/summary.json`.
- `SystemCollector` (new): psutil — cpu %, mem, disk usage (`/` or configured mounts), disk I/O
  rates, net rates; keep short ring buffers for the graphs.
- Unit tests with fixture transcripts/headers (the parsing logic is the most regression-prone part).

### Phase 3 — Renderer
- Pillow-based frame builder targeting the **sink-reported** resolution; design at 1920×462 and
  make regions proportional so 1280×480/1920×440 still work.
- Dark theme (the LCD is inside a case window — dark background, high-contrast accents, orange/blue
  bars matching the current widgets). Bundle a good font (e.g. Inter/DejaVu) — don't depend on
  system font lookup inside a systemd service.
- Components: progress bar, sparkline, dual-line rate graph, big-number stat, status dot, text
  rows. Explicit "STALE"/error rendering per panel.
- `trcc-monitor preview` renders with live (or `--mock`) data to PNG → fast iteration with zero
  hardware. This is the main dev loop until the display is installed.

### Phase 4 — Device output via trccd
- `TrccdSink`: discover device key (`GET /devices`), read resolution, `POST
  .../display/send-image` each tick (JPEG upload; trccd handles wire encode + keepalive).
  Decide REST vs raw IPC after measuring — REST is simpler; IPC (`trcc.ipc` JSON-lines on the Unix
  socket, base64 `SendImage`) avoids running the HTTP server. Prefer whichever lets trccd stay in
  its default loopback/no-auth or socket-only posture.
- Update cadence: render+push ~1 Hz for system stats; Claude data changes slower. Push only when
  the rendered frame actually changed (hash) to keep CPU near zero — trccd's keepalive maintains
  the panel in between.
- Resilience: trccd restart / device unplug / suspend-resume → sink reconnects with backoff and
  the service keeps running.

### Phase 5 — systemd user service
- `trcc-monitor.service` (user unit): `After=trccd.service` + `Wants=trccd.service`,
  `Restart=on-failure`, `ExecStart=trcc-monitor run`. No graphical-session dependency —
  must run on a headless boot.
- `install.sh` / `just install`: install package, drop unit into `~/.config/systemd/user/`,
  `daemon-reload`, enable. One command from clone to glowing screen.
- Journal-friendly logging; `trcc-monitor check` as the documented debug entry point.

### Phase 6 — Polish
- Port the widget's notification thresholds (`notify-send` on 90% / limit reached / new incident) —
  the LCD shows state, but pushes still matter when you're not looking at the case.
- Screen-off / dim schedule (night hours → `POST .../display/sleep` or a black frame).
- Layout config: enable/disable/reorder panels from config.toml without code changes.
- On-screen fallback frame when collectors are totally dead (e.g. big "token expired — run claude").

### Phase 7 (stretch) — Standalone LY sender
Drop the trcc-linux dependency: implement `LySink` directly with pyusb — the protocol is small and
fully documented in `ly_lcd.py` (2048-byte handshake → 512-byte response → PM/SUB → resolution;
512-byte chunks with 16-byte headers in 4096-byte writes; JPEG payload; 150 ms keepalive thread;
pad-to-4-chunks for PID 5408). Only worth it if carrying trcc-linux (PySide6 etc.) proves annoying
on Bazzite. The sink abstraction from Phase 4 makes this a drop-in.

## Open questions / decisions to make

1. **REST vs IPC to trccd** — decide in Phase 4; default lean: IPC socket (no open TCP port, no
   second server process inside trccd).
2. **API probe cadence** — every probe burns a real (1-token) request; widget default is
   per-minute-ish. Suggest 5 min default, configurable, with burn-rate math tolerant of gaps.
3. **Panel orientation** — LY supports 0°/180° only; confirm mounting orientation once installed.
4. **Bazzite packaging** — pipx vs distrobox vs layered; affects both trcc-linux and our package.
5. **Do system metrics stay?** Primary goal is Claude data; system stats are cheap to add via
   psutil, but if the layout gets cramped at 462 px tall, Claude data wins.

## Milestones

- **M1** (Phases 1–3): `trcc-monitor preview` produces a complete 1920×462 dashboard PNG from live
  local data — no hardware needed.
- **M2** (Phase 4): frame visible on the physical display via trccd.
- **M3** (Phase 5): survives reboot untouched — `systemctl --user status trcc-monitor` green,
  display live.
- **M4** (Phase 6): daily-driver quality; KDE widgets removed from the desktop.
