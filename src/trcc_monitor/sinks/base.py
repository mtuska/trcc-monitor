"""Sink interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class SinkError(Exception):
    """A sink failed to connect or push a frame."""


class Sink(ABC):
    """Destination for rendered dashboard frames."""

    @abstractmethod
    def connect(self) -> None:
        """Prepare the sink (open the device, discover resolution). May raise."""

    @abstractmethod
    def resolution(self) -> tuple[int, int] | None:
        """Target resolution to render at, or None to use the design default."""

    @abstractmethod
    def push(self, image: Image.Image) -> None:
        """Send one frame. May raise :class:`SinkError` on failure."""

    def close(self) -> None:
        """Release resources. Default: no-op."""

    def __enter__(self) -> "Sink":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
