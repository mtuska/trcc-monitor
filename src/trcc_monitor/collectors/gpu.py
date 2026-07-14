"""GPU metrics — NVIDIA (nvidia-smi) or AMD (sysfs), whichever is primary.

New for trcc-monitor. Detection order:

* **NVIDIA** — ``nvidia-smi`` (no extra Python dependency) for utilization,
  VRAM, temperature, and power.
* **AMD** — the amdgpu sysfs interface under ``/sys/class/drm/card*/device``
  (``gpu_busy_percent``, ``mem_info_vram_used/total``, hwmon ``temp*_input``).
  No tools required; works headless.

Returns ``{"available": False}`` rather than raising when no supported GPU is
present, so the renderer just omits the GPU tiles. All payloads share one shape
regardless of vendor.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Any

from .base import Collector

_NVIDIA_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,name"


def _payload(name, usage, vram_used, vram_total, temp, power, vendor):
    return {
        "available": True,
        "vendor": vendor,
        "name": name,
        "usage_percent": usage,
        "vram_used": vram_used,
        "vram_total": vram_total,
        "vram_percent": (vram_used / vram_total * 100.0) if vram_total > 0 else 0.0,
        "temp": temp,
        "power": power,
    }


# ── NVIDIA ─────────────────────────────────────────────────────────────
def _query_nvidia(smi: str) -> dict[str, Any] | None:
    try:
        out = subprocess.run(
            [smi, f"--query-gpu={_NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    def num(s: str) -> float:
        try:
            return float(s)
        except ValueError:
            return 0.0  # "[N/A]" for unsupported fields

    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        util, mem_used, mem_total, temp, power, name = parts[:6]
        return _payload(
            name=name, usage=num(util),
            vram_used=num(mem_used) * 2**20, vram_total=num(mem_total) * 2**20,
            temp=num(temp), power=num(power), vendor="nvidia",
        )
    return None


# ── AMD (amdgpu sysfs) ─────────────────────────────────────────────────
def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _read_str(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _find_amd_card() -> str | None:
    """Return the device dir of the first AMD GPU exposing busy percent."""
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        if os.path.exists(os.path.join(card, "gpu_busy_percent")):
            return card
    return None


def _query_amd(device: str) -> dict[str, Any] | None:
    busy = _read_int(os.path.join(device, "gpu_busy_percent"))
    if busy is None:
        return None
    used = _read_int(os.path.join(device, "mem_info_vram_used")) or 0
    total = _read_int(os.path.join(device, "mem_info_vram_total")) or 0

    # Temperature from the amdgpu hwmon node (millidegrees C).
    temp = 0.0
    for tpath in glob.glob(os.path.join(device, "hwmon", "hwmon*", "temp1_input")):
        milli = _read_int(tpath)
        if milli is not None:
            temp = milli / 1000.0
            break

    # Average power (microwatts) if the hwmon node exposes it.
    power = 0.0
    for ppath in glob.glob(os.path.join(device, "hwmon", "hwmon*", "power1_average")):
        micro = _read_int(ppath)
        if micro is not None:
            power = micro / 1_000_000.0
            break

    name = _read_str(os.path.join(device, "product_name")) or "AMD GPU"
    return _payload(
        name=name, usage=float(busy), vram_used=used, vram_total=total,
        temp=temp, power=power, vendor="amd",
    )


class GpuCollector(Collector):
    name = "gpu"
    interval = 2.0

    def __init__(self, interval: float | None = None) -> None:
        super().__init__(interval)
        self._nvidia_smi = shutil.which("nvidia-smi")
        self._amd_card = _find_amd_card()

    def poll(self) -> dict[str, Any]:
        if self._nvidia_smi:
            data = _query_nvidia(self._nvidia_smi)
            if data:
                return data
        if self._amd_card:
            data = _query_amd(self._amd_card)
            if data:
                return data
        # Re-probe once in case the AMD card appeared after startup.
        card = _find_amd_card()
        if card:
            self._amd_card = card
            data = _query_amd(card)
            if data:
                return data
        return {"available": False}
