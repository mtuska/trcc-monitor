"""Tests for the GPU collector (NVIDIA parse + AMD sysfs)."""
import os

from trcc_monitor.collectors.gpu import GpuCollector, _query_amd
from trcc_monitor.render.frame import _short_gpu


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_amd_sysfs_parse(tmp_path):
    dev = tmp_path / "device"
    _write(str(dev / "gpu_busy_percent"), "37\n")
    _write(str(dev / "mem_info_vram_used"), str(2 * 2**30) + "\n")
    _write(str(dev / "mem_info_vram_total"), str(8 * 2**30) + "\n")
    _write(str(dev / "hwmon" / "hwmon3" / "temp1_input"), "52000\n")
    _write(str(dev / "hwmon" / "hwmon3" / "power1_average"), "95000000\n")
    _write(str(dev / "product_name"), "AMD Radeon RX 7900 XTX\n")

    out = _query_amd(str(dev))
    assert out["available"] is True
    assert out["vendor"] == "amd"
    assert out["usage_percent"] == 37.0
    assert out["vram_used"] == 2 * 2**30
    assert out["vram_total"] == 8 * 2**30
    assert out["vram_percent"] == 25.0
    assert out["temp"] == 52.0
    assert out["power"] == 95.0
    assert "Radeon" in out["name"]


def test_amd_missing_busy_returns_none(tmp_path):
    dev = tmp_path / "device"
    dev.mkdir()
    assert _query_amd(str(dev)) is None


def test_unavailable_when_no_gpu(monkeypatch):
    # Force both backends absent.
    import trcc_monitor.collectors.gpu as gpu
    monkeypatch.setattr(gpu.shutil, "which", lambda _: None)
    monkeypatch.setattr(gpu, "_find_amd_card", lambda: None)
    out = GpuCollector().poll()
    assert out == {"available": False}


def test_short_gpu_name():
    assert _short_gpu("NVIDIA GeForce RTX 4090") == "RTX 4090"
    assert _short_gpu("AMD Radeon RX 7900 XTX") == "Radeon RX 7900 XTX"
    assert _short_gpu("Intel Arc A770") == "Arc A770"
    assert _short_gpu("Mystery Accelerator") == "Mystery Accelerator"
