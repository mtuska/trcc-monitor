"""Tests for sinks: PNG output and trccd device-selection/parsing logic."""
import pytest
from PIL import Image

from trcc_monitor import config as config_mod
from trcc_monitor.sinks import build_sink
from trcc_monitor.sinks.base import SinkError
from trcc_monitor.sinks.png import PngSink
from trcc_monitor.sinks.trccd import TrccdSink, _key_from


def _cfg(**sink_kw):
    base = config_mod.Config()
    return config_mod.replace(base, sink=config_mod.replace(base.sink, **sink_kw))


def test_png_sink_writes(tmp_path):
    cfg = _cfg(kind="png", png_path=str(tmp_path / "out.png"))
    sink = build_sink(cfg)
    assert isinstance(sink, PngSink)
    sink.connect()
    sink.push(Image.new("RGB", (100, 40), (10, 20, 30)))
    assert sink.path.is_file()
    assert Image.open(sink.path).size == (100, 40)


def test_png_sink_resolution_is_none(tmp_path):
    sink = PngSink(_cfg(kind="png", png_path=str(tmp_path / "o.png")))
    assert sink.resolution() is None


def test_key_from():
    assert _key_from(0x0416, 0x5408) == "0416:5408"


def test_select_device_prefers_lcd():
    sink = TrccdSink(_cfg(kind="trccd"))
    devices = [
        {"vid": 0x0416, "pid": 0x8001},   # LED controller (0,0 res)
        {"vid": 0x0416, "pid": 0x5408},   # Trofeo Vision LCD
    ]
    products = [
        {"vid": 0x0416, "pid": 0x8001, "native_resolution": [0, 0]},
        {"vid": 0x0416, "pid": 0x5408, "native_resolution": [1920, 462]},
    ]
    assert sink._select_device(devices, products) == "0416:5408"


def test_select_device_honors_configured_key():
    sink = TrccdSink(_cfg(kind="trccd", device_key="0416:5409"))
    assert sink._select_device([], []) == "0416:5409"


def test_select_device_none_found_raises():
    sink = TrccdSink(_cfg(kind="trccd"))
    with pytest.raises(SinkError):
        sink._select_device([], [])


def test_parse_resolution():
    assert TrccdSink._parse_resolution({"resolution": [1920, 462]}) == (1920, 462)
    assert TrccdSink._parse_resolution({"resolution": None}) is None
    assert TrccdSink._parse_resolution(None) is None


def test_to_framebuffer_rotation():
    img = Image.new("RGB", (1920, 462))
    # 0 and 180 preserve dimensions; 90/270 swap them.
    assert TrccdSink(_cfg(kind="trccd", rotate=0))._to_framebuffer(img).size == (1920, 462)
    assert TrccdSink(_cfg(kind="trccd", rotate=180))._to_framebuffer(img).size == (1920, 462)
    assert TrccdSink(_cfg(kind="trccd", rotate=90))._to_framebuffer(img).size == (462, 1920)


def test_resolution_not_swapped_by_rotate():
    # Rotation is applied to the finished frame, not by swapping render size.
    sink = TrccdSink(_cfg(kind="trccd", rotate=180))
    sink._resolution = (1920, 462)
    assert sink.resolution() == (1920, 462)


def test_trccd_connect_without_daemon_raises(tmp_path, monkeypatch):
    # No socket present → connect should raise SinkError, not hang or crash.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    sink = TrccdSink(_cfg(kind="trccd", transport="ipc"))
    with pytest.raises(SinkError):
        sink.connect()
