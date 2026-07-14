"""Tests for the sessions (active-agent) counter."""
import os
import time

from trcc_monitor.collectors.sessions import count_sessions


def _touch(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    os.utime(path, (mtime, mtime))


def test_empty(tmp_path):
    assert count_sessions(tmp_path, now=time.time()) == {"agents": 0, "subagents": 0}


def test_fresh_agent_counted(tmp_path):
    now = time.time()
    _touch(tmp_path / "proj" / "a.jsonl", now - 5)      # fresh
    _touch(tmp_path / "proj" / "b.jsonl", now - 120)    # stale
    out = count_sessions(tmp_path, now=now, window=30)
    assert out == {"agents": 1, "subagents": 0}


def test_subagent_bucket(tmp_path):
    now = time.time()
    _touch(tmp_path / "proj" / "main.jsonl", now - 2)
    _touch(tmp_path / "proj" / "subagents" / "s1.jsonl", now - 2)
    _touch(tmp_path / "proj" / "subagents" / "s2.jsonl", now - 2)
    out = count_sessions(tmp_path, now=now, window=30)
    assert out == {"agents": 1, "subagents": 2}


def test_window_boundary(tmp_path):
    now = time.time()
    _touch(tmp_path / "p" / "edge.jsonl", now - 30)
    assert count_sessions(tmp_path, now=now, window=30)["agents"] == 1
    assert count_sessions(tmp_path, now=now, window=29)["agents"] == 0
