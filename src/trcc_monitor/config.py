"""Configuration for trcc-monitor.

Loaded from ``~/.config/trcc-monitor/config.toml`` (or ``$TRCC_MONITOR_CONFIG``),
falling back to defaults for anything unset. All intervals are in seconds unless
noted. The API-probe interval matters most: each probe is a real (1-token) call
to api.anthropic.com, so keep it comfortably long.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def _default_config_path() -> Path:
    env = os.environ.get("TRCC_MONITOR_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return Path(base) / "trcc-monitor" / "config.toml"


@dataclass(frozen=True)
class Intervals:
    """How often each collector refreshes, in seconds."""

    limits: float = 300.0     # API rate-limit probe — burns one 1-token call each time
    usage: float = 60.0       # local transcript scan for tokens/cost
    sessions: float = 10.0    # local transcript mtime scan for active agents
    status: float = 120.0     # status.claude.com summary
    system: float = 2.0       # psutil cpu/mem/disk/net
    gpu: float = 2.0          # nvidia-smi / amdgpu sysfs
    render: float = 1.0       # frame render + push cadence


@dataclass(frozen=True)
class Proxy:
    """Proxy behavior for the two outbound HTTP calls (limits, status)."""

    mode: str = "env"          # "none" | "env" | "custom"
    url: str = ""              # used when mode == "custom"


@dataclass(frozen=True)
class Sink:
    """Where rendered frames go."""

    kind: str = "trccd"        # "trccd" | "png"
    device_key: str = ""       # trccd device key; empty = auto-select first LCD
    transport: str = "auto"    # "auto" | "rest" | "ipc"
    rest_base_url: str = "http://127.0.0.1:8000"
    png_path: str = ""         # for kind == "png"; empty = scratch/preview.png
    # Clockwise degrees to rotate the rendered frame before sending, for panels
    # physically mounted rotated. 90/270 also swap the render dimensions so the
    # dashboard is composed in the viewer's orientation. The Trofeo Vision LY
    # (only 0/180 in firmware) mounted vertically needs 90.
    rotate: int = 0            # 0 | 90 | 180 | 270


@dataclass(frozen=True)
class Config:
    claude_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CLAUDE_DIR", os.path.expanduser("~/.claude"))
        )
    )
    intervals: Intervals = field(default_factory=Intervals)
    proxy: Proxy = field(default_factory=Proxy)
    sink: Sink = field(default_factory=Sink)
    # Panels to render, in order. Unknown names are ignored by the renderer.
    panels: tuple[str, ...] = (
        "limits",
        "usage",
        "sessions",
        "status",
        "system",
        "gpu",
    )
    session_window_s: float = 30.0   # transcript mtime freshness for "working now"
    # Filesystem to report disk usage for. Defaults to the home dir rather than
    # "/", since on immutable/ostree distros (Bazzite) "/" is a full read-only
    # deployment root and reports a useless 100%.
    disk_path: str = field(default_factory=lambda: os.path.expanduser("~"))

    @property
    def credentials_file(self) -> Path:
        return self.claude_dir / ".credentials.json"

    @property
    def projects_dir(self) -> Path:
        return self.claude_dir / "projects"


def _apply_section(obj, data: dict):
    """Return a copy of a frozen dataclass with keys from ``data`` overlaid."""
    valid = {f.name for f in fields(obj)}
    updates = {k: v for k, v in data.items() if k in valid}
    return replace(obj, **updates) if updates else obj


def load(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults. Missing file → defaults."""
    cfg_path = path or _default_config_path()
    cfg = Config()
    if not cfg_path.is_file():
        return cfg

    with open(cfg_path, "rb") as f:
        raw = tomllib.load(f)

    top: dict = {}
    if "claude_dir" in raw:
        top["claude_dir"] = Path(str(raw["claude_dir"])).expanduser()
    if "panels" in raw:
        top["panels"] = tuple(raw["panels"])
    if "session_window_s" in raw:
        top["session_window_s"] = float(raw["session_window_s"])
    if "disk_path" in raw:
        top["disk_path"] = str(Path(str(raw["disk_path"])).expanduser())

    if isinstance(raw.get("intervals"), dict):
        top["intervals"] = _apply_section(cfg.intervals, raw["intervals"])
    if isinstance(raw.get("proxy"), dict):
        top["proxy"] = _apply_section(cfg.proxy, raw["proxy"])
    if isinstance(raw.get("sink"), dict):
        sink_raw = dict(raw["sink"])
        if "rotate" in sink_raw:
            sink_raw["rotate"] = int(sink_raw["rotate"]) % 360
        top["sink"] = _apply_section(cfg.sink, sink_raw)

    return replace(cfg, **top)
