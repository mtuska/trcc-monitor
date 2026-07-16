"""Tests for config loading."""
from pathlib import Path

from trcc_monitor import config as config_mod


def test_defaults_when_missing(tmp_path):
    cfg = config_mod.load(tmp_path / "does-not-exist.toml")
    assert cfg.intervals.limits == 300.0   # 5 min — free authenticated GET
    assert cfg.proxy.mode == "env"
    assert cfg.sink.kind == "trccd"
    assert "limits" in cfg.panels


def test_partial_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'panels = ["system"]\n'
        "session_window_s = 45\n"
        "[intervals]\n"
        "limits = 600\n"
        "[proxy]\n"
        'mode = "custom"\n'
        'url = "http://proxy:8080"\n'
        "[sink]\n"
        'kind = "png"\n'
    )
    cfg = config_mod.load(p)
    assert cfg.panels == ("system",)
    assert cfg.session_window_s == 45.0
    assert cfg.intervals.limits == 600.0
    # unspecified interval keeps default
    assert cfg.intervals.usage == 60.0
    assert cfg.proxy.mode == "custom"
    assert cfg.proxy.url == "http://proxy:8080"
    assert cfg.sink.kind == "png"


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[intervals]\nbogus_key = 5\nlimits = 100\n")
    cfg = config_mod.load(p)
    assert cfg.intervals.limits == 100.0
    assert not hasattr(cfg.intervals, "bogus_key")


def test_derived_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'claude_dir = "{tmp_path}/dotclaude"\n')
    cfg = config_mod.load(p)
    assert cfg.credentials_file == Path(f"{tmp_path}/dotclaude/.credentials.json")
    assert cfg.projects_dir == Path(f"{tmp_path}/dotclaude/projects")
