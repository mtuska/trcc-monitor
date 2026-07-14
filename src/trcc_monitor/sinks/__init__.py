"""Frame sinks: where a rendered dashboard image goes.

A sink hides the difference between "write a PNG to disk" (development) and
"push to the LCD via the trccd daemon" (production). Everything above the sink
is hardware-agnostic.
"""
from .base import Sink, SinkError
from .png import PngSink
from .trccd import TrccdSink

__all__ = ["Sink", "SinkError", "PngSink", "TrccdSink", "build_sink"]


def build_sink(config) -> Sink:
    """Construct the sink named by ``config.sink.kind``."""
    kind = config.sink.kind
    if kind == "png":
        return PngSink(config)
    if kind == "trccd":
        return TrccdSink(config)
    raise SinkError(f"unknown sink kind: {kind!r}")
