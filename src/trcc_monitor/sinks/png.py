"""PNG sink — writes each frame to a file. For development without hardware."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from ..config import Config
from .base import Sink, SinkError


class PngSink(Sink):
    def __init__(self, config: Config) -> None:
        path = config.sink.png_path
        if not path:
            runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
            path = os.path.join(runtime, "trcc-monitor", "preview.png")
        self._path = Path(path).expanduser()

    def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def resolution(self) -> tuple[int, int] | None:
        return None  # render at design resolution

    def push(self, image: Image.Image) -> None:
        try:
            # Write atomically so a reader never sees a half-written file.
            tmp = self._path.with_suffix(".png.tmp")
            image.save(tmp, format="PNG")
            os.replace(tmp, self._path)
        except OSError as e:
            raise SinkError(f"PNG write failed: {e}") from e

    @property
    def path(self) -> Path:
        return self._path
