"""trccd sink — push frames to the LCD through the thermalright-trcc-linux daemon.

The daemon (``trcc daemon``) owns the USB device: handshake, the LY chunked wire
protocol, and the ~150 ms keepalive that stops the panel reverting to its boot
logo. It auto-connects the device on startup.

We send frames with the **SendFrame** command — raw pre-encoded JPEG bytes that
go straight to the wire. This deliberately bypasses the daemon's ``SendImage``
pipeline, which hard-resizes to the profile resolution and applies its own
device-side 90° rotation (``_apply_post_processing`` / ``build_image_frame`` in
trcc-linux) — that mangled our already-correct frames. With SendFrame we own the
exact pixels: render landscape at the device resolution, apply ``sink.rotate``
(this panel is mounted 180°), encode JPEG, ship it. No resize, no daemon rotate.

Transport is the daemon's Unix-socket IPC (``$XDG_RUNTIME_DIR/trcc.sock``): one
newline-delimited JSON object per request, ``{"command": "<Name>", "kwargs":
{...}}`` → ``{"type": "...", "ok": ...}``; binary payloads travel as
``{"__bytes__": "<base64>"}``. We reimplement just the client side so
trcc-monitor doesn't depend on importing the (heavy, PySide6-pulling) trcc
package. A REST fallback exists but goes through the daemon's SendImage pipeline,
so it is subject to the resize/rotate above — prefer IPC.

Device selection: the configured ``sink.device_key`` if set, else the first
discovered device whose product has a non-zero native resolution (an LCD, not
the LED controller). The device key is ``{vid:04x}:{pid:04x}``.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import socket
from pathlib import Path

from PIL import Image

from ..config import Config
from .base import Sink, SinkError

_JPEG_QUALITY = 90

log = logging.getLogger(__name__)

_SOCK_NAME = "trcc.sock"
_TIMEOUT_S = 30.0


def _socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(runtime) / _SOCK_NAME


def _key_from(vid: int, pid: int) -> str:
    return f"{vid:04x}:{pid:04x}"


# ── Minimal IPC client ─────────────────────────────────────────────────
class _IpcClient:
    """One-shot request client for the trccd Unix socket."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _socket_path()

    def available(self) -> bool:
        if not self._path.exists():
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(str(self._path))
            return True
        except OSError:
            return False

    def request(self, command: str, kwargs: dict, timeout: float = _TIMEOUT_S) -> dict:
        payload = json.dumps({"command": command, "kwargs": kwargs}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(str(self._path))
                s.sendall(payload)
                data = self._recv_line(s)
        except OSError as e:
            raise SinkError(f"trccd IPC {command} failed: {e}") from e
        try:
            resp = json.loads(data.decode())
        except (ValueError, UnicodeDecodeError) as e:
            raise SinkError(f"trccd IPC bad response to {command}: {e}") from e
        if not resp.get("ok", False):
            raise SinkError(
                f"trccd {command} rejected: {resp.get('message', 'no message')}"
            )
        return resp

    @staticmethod
    def _recv_line(s: socket.socket, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        chunks: list[bytes] = []
        received = 0
        while received < max_bytes:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if b"\n" in chunk:
                break
        line = b"".join(chunks).split(b"\n", 1)[0]
        if not line:
            raise SinkError("trccd closed the connection without responding")
        return line


# ── Sink ───────────────────────────────────────────────────────────────
class TrccdSink(Sink):
    def __init__(self, config: Config) -> None:
        self._cfg = config.sink
        self._transport = self._cfg.transport
        self._ipc = _IpcClient()
        self._key: str | None = config.sink.device_key or None
        self._rotate: int = config.sink.rotate % 360
        # Device framebuffer resolution (from handshake/discovery).
        self._resolution: tuple[int, int] | None = None

    # -- transport resolution ------------------------------------------
    def _use_ipc(self) -> bool:
        if self._transport == "ipc":
            return True
        if self._transport == "rest":
            return False
        return self._ipc.available()  # "auto"

    # -- lifecycle ------------------------------------------------------
    def connect(self) -> None:
        if self._use_ipc():
            self._connect_ipc()
        else:
            self._connect_rest()

    def _connect_ipc(self) -> None:
        if not self._ipc.available():
            raise SinkError(
                f"trccd socket not found at {self._ipc._path} — is the daemon "
                "running? (systemctl --user start trccd.service)"
            )
        disc = self._ipc.request("DiscoverDevices", {})
        products = disc.get("products", [])
        key = self._select_device(disc.get("devices", []), products)
        # EnsureConnected is idempotent: the daemon auto-connects the device on
        # startup, so a plain ConnectDevice would collide with its own handle
        # ("in use"). EnsureConnected returns ok even when already connected.
        conn = self._ipc.request("EnsureConnected", {"key": key})
        self._key = key
        # When already connected, EnsureConnected returns no fresh handshake, so
        # fall back to the device's native resolution from discovery.
        self._resolution = (self._parse_resolution(conn.get("handshake"))
                            or self._resolution_for(key, products))
        log.info("trccd IPC connected: key=%s resolution=%s", key, self._resolution)

    def _connect_rest(self) -> None:
        import httpx

        base = self._cfg.rest_base_url.rstrip("/")
        self._rest_base = base
        try:
            with httpx.Client(timeout=10.0, trust_env=False) as c:
                r = c.get(f"{base}/devices")
                r.raise_for_status()
                devices = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SinkError(f"trccd REST /devices failed: {e}") from e
        # REST returns a list of device dicts; normalize to the fields we need.
        devs = devices.get("devices", devices) if isinstance(devices, dict) else devices
        key = self._select_device(devs, devs)
        try:
            with httpx.Client(timeout=10.0, trust_env=False) as c:
                r = c.post(f"{base}/devices/{key}/connect")
                r.raise_for_status()
                conn = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SinkError(f"trccd REST connect failed: {e}") from e
        self._key = key
        self._resolution = self._parse_resolution(conn.get("handshake"))
        log.info("trccd REST connected: key=%s resolution=%s", key, self._resolution)

    # -- device selection ----------------------------------------------
    def _select_device(self, devices: list, products: list) -> str:
        if self._key:
            return self._key
        # Products carry native_resolution; an LCD has a non-zero one, the LED
        # controller is (0, 0). Prefer the first LCD.
        lcd_keys = set()
        for p in products or []:
            res = p.get("native_resolution") or [0, 0]
            if tuple(res) != (0, 0) and "vid" in p and "pid" in p:
                lcd_keys.add(_key_from(p["vid"], p["pid"]))
        for dev in devices or []:
            if "vid" not in dev or "pid" not in dev:
                continue
            k = _key_from(dev["vid"], dev["pid"])
            if not lcd_keys or k in lcd_keys:
                return k
        raise SinkError("no LCD device found by trccd (is the panel plugged in?)")

    @staticmethod
    def _resolution_for(key: str, products: list) -> tuple[int, int] | None:
        for p in products or []:
            if "vid" in p and "pid" in p and _key_from(p["vid"], p["pid"]) == key:
                res = p.get("native_resolution")
                if isinstance(res, (list, tuple)) and len(res) == 2:
                    return (int(res[0]), int(res[1]))
        return None

    @staticmethod
    def _parse_resolution(handshake) -> tuple[int, int] | None:
        if not isinstance(handshake, dict):
            return None
        res = handshake.get("resolution")
        if isinstance(res, (list, tuple)) and len(res) == 2:
            return (int(res[0]), int(res[1]))
        return None

    # -- Sink API -------------------------------------------------------
    def resolution(self) -> tuple[int, int] | None:
        # Always render landscape at the device resolution; rotation is applied
        # to the finished frame in _to_framebuffer (SendFrame ships it raw, so a
        # 90/270 rotation just changes the JPEG dimensions — no daemon resize).
        return self._resolution

    def _to_framebuffer(self, image: Image.Image) -> Image.Image:
        """Rotate the rendered frame clockwise by ``self._rotate`` to match how
        the panel is physically mounted (this panel needs 180)."""
        transpose = {
            90: Image.ROTATE_270,   # 90° clockwise
            180: Image.ROTATE_180,
            270: Image.ROTATE_90,   # 90° counter-clockwise
        }.get(self._rotate)
        return image.transpose(transpose) if transpose else image

    def push(self, image: Image.Image) -> None:
        if self._key is None:
            raise SinkError("push before connect")
        if self._use_ipc():
            self._push_ipc(image)
        else:
            self._push_rest(image)

    def _push_ipc(self, image: Image.Image) -> None:
        # Encode the (rotated) frame as JPEG and ship the raw bytes straight to
        # the wire via SendFrame — no daemon resize/rotate.
        image = self._to_framebuffer(image)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=_JPEG_QUALITY)
        payload = {"__bytes__": base64.b64encode(buf.getvalue()).decode("ascii")}
        self._ipc.request("SendFrame", {"key": self._key, "data": payload})

    def _push_rest(self, image: Image.Image) -> None:
        import io

        import httpx

        buf = io.BytesIO()
        self._to_framebuffer(image).save(buf, format="PNG")
        buf.seek(0)
        url = f"{self._rest_base}/devices/{self._key}/display/send-image"
        try:
            with httpx.Client(timeout=10.0, trust_env=False) as c:
                r = c.post(url, files={"file": ("frame.png", buf, "image/png")})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise SinkError(f"trccd REST send-image failed: {e}") from e
