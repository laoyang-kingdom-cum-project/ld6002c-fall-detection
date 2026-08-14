"""Business event model and CSV logger."""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .device_protocol import DeviceState


EventName = Literal[
    "FALL_SUSPECTED",
    "FALL_CONFIRMED",
    "ALARM_STARTED",
    "ALARM_CANCELLED",
    "DEVICE_CONNECTED",
    "DEVICE_DISCONNECTED",
]


@dataclass(frozen=True)
class SystemEvent:
    """One meaningful business or device event."""

    timestamp: datetime
    event: EventName
    state: DeviceState
    source: str
    details: str = ""


class CSVEventLogger:
    """Append system events to a thread-safe CSV file."""

    fieldnames = ["timestamp", "event", "state", "source", "details"]

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            self._ensure_header()

    def log(self, event: SystemEvent) -> None:
        timestamp = (
            event.timestamp if event.timestamp.tzinfo else event.timestamp.astimezone()
        )
        row = {
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "event": event.event,
            "state": event.state,
            "source": event.source,
            "details": event.details,
        }
        try:
            with self._lock, self.log_path.open("a", newline="", encoding="utf-8") as file:
                csv.DictWriter(file, fieldnames=self.fieldnames).writerow(row)
        except OSError as exc:
            raise RuntimeError(f"Failed to write event log {self.log_path}: {exc}") from exc

    def _ensure_header(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            return
        try:
            with self.log_path.open("w", newline="", encoding="utf-8") as file:
                csv.DictWriter(file, fieldnames=self.fieldnames).writeheader()
        except OSError as exc:
            raise RuntimeError(f"Failed to create event log {self.log_path}: {exc}") from exc
