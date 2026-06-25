"""Common data model used by all radar readers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RadarFrame:
    """One normalized radar observation.

    Serial parsing and mock generation should both convert their output into
    this structure before the data enters the fall detection state machine.
    """

    timestamp: datetime
    human_present: bool
    fall_detected: bool
    motion_state: str
    raw: str
