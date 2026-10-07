"""Opt-in synthetic clock candidate. Importing never mounts routes or starts work."""
from .clock import DemoBusinessClock, DemoClockSettings

__all__ = ["DemoBusinessClock", "DemoClockSettings"]
