"""Command-line entry point for trcc-monitor.

Subcommands:
  check    — poll every collector once, print the results as JSON, and exit.
  preview  — render one dashboard frame to a PNG and exit (Phase 3).
  run      — start collectors and drive the display in a loop (Phase 3/4).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, config as config_mod
from .app import build_dashboard, link_resets


def _load_config(args) -> config_mod.Config:
    path = Path(args.config).expanduser() if args.config else None
    return config_mod.load(path)


def cmd_check(args) -> int:
    """Poll every collector once synchronously and print JSON."""
    cfg = _load_config(args)
    dash, collectors = build_dashboard(cfg)

    # Poll limits first so usage can align its windows to the reset timestamps.
    order = ["limits", "usage", "sessions", "status", "system"]
    ordered = [n for n in order if n in dash.runners]
    ordered += [n for n in dash.runners if n not in ordered]

    out: dict = {}
    for name in ordered:
        runner = dash.runners[name]
        if name != "limits":
            link_resets(collectors)
        snap = runner.poll_once()
        out[name] = {
            "ok": snap.ok,
            "error": snap.error,
            "age_s": None if snap.updated_at == 0 else round(snap.age(), 2),
            "data": snap.data,
        }

    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0 if all(v["ok"] for v in out.values()) else 1


def cmd_preview(args) -> int:
    """Render one frame to PNG. Implemented in Phase 3 (renderer)."""
    try:
        from .render.frame import render_preview
    except ImportError:
        print("preview: renderer not yet available (Phase 3)", file=sys.stderr)
        return 2
    cfg = _load_config(args)
    out_path = render_preview(cfg, mock=args.mock, out_path=args.output)
    print(f"wrote {out_path}")
    return 0


def cmd_run(args) -> int:
    """Start collectors and drive the display until signalled to stop."""
    import logging

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from .runner import run_loop

    cfg = _load_config(args)
    return run_loop(cfg)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trcc-monitor", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "-c", "--config", help="path to config.toml (default: XDG config dir)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="poll collectors once and print JSON").set_defaults(
        func=cmd_check
    )

    pv = sub.add_parser("preview", help="render one frame to PNG and exit")
    pv.add_argument("-o", "--output", help="output PNG path")
    pv.add_argument(
        "--mock", action="store_true", help="use mock data instead of live collectors"
    )
    pv.set_defaults(func=cmd_preview)

    rn = sub.add_parser("run", help="run the collect+render+display loop")
    rn.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    rn.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
