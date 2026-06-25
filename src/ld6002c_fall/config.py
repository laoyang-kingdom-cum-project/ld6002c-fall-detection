"""Application defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOG_PATH = Path("data/fall_log.csv")
DEFAULT_BAUDRATE = 115200
DEFAULT_SUSPECT_SECONDS = 2.0
DEFAULT_CONFIRM_SECONDS = 5.0
DEFAULT_ALARM_COOLDOWN = 30.0


@dataclass(frozen=True)
class DetectorConfig:
    """Configuration for the Python secondary decision logic."""

    suspect_seconds: float = DEFAULT_SUSPECT_SECONDS
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS
    alarm_cooldown: float = DEFAULT_ALARM_COOLDOWN
