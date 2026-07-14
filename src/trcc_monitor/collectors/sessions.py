"""Count Claude Code agents actively working on this machine.

Ported from the KDE widget's ``fetch_sessions.sh``. "Actively working" is
inferred from transcript write recency: Claude Code streams to the transcript
while generating and stops when idle. Purely local, no network, no API tokens.
Only sees work on this machine, not chats on claude.ai or other devices.
"""
from __future__ import annotations

import glob
import os
import time
from pathlib import Path
from typing import Any

from .base import Collector


def count_sessions(
    projects_dir: str | os.PathLike, now: float, window: float = 30.0
) -> dict[str, int]:
    """Count top-level agents and sub-agents whose transcript is fresh.

    A transcript written within ``window`` seconds means that agent is
    currently generating. Sub-agents live under a ``.../subagents/`` path.
    Pure; ``now`` is injectable for tests.
    """
    proj = os.fspath(projects_dir)
    sep = os.sep
    agents = 0
    subagents = 0
    for path in glob.glob(os.path.join(proj, "**", "*.jsonl"), recursive=True):
        try:
            if (now - os.path.getmtime(path)) > window:
                continue
        except OSError:
            continue
        if (sep + "subagents" + sep) in path:
            subagents += 1
        else:
            agents += 1
    return {"agents": agents, "subagents": subagents}


class SessionsCollector(Collector):
    name = "sessions"
    interval = 10.0

    def __init__(
        self, projects_dir: Path, window: float = 30.0, interval: float | None = None
    ) -> None:
        super().__init__(interval)
        self._projects_dir = projects_dir
        self._window = window

    def poll(self) -> dict[str, Any]:
        return count_sessions(self._projects_dir, time.time(), self._window)
