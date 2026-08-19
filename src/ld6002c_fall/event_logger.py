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
    "FALL_DETECTED",
    "ALARM_TRIGGERED",
    "ALARM_CANCELLED",
    "DEVICE_CONNECTED",
    "DEVICE_DISCONNECTED",
    "AI_REQUEST",
    "AI_RESPONSE",
    "AI_ERROR",
    "AI_FALLBACK",
]


@dataclass(frozen=True)
class SystemEvent:
    """One meaningful business or device event."""

    timestamp: datetime
    event: EventName
    state: DeviceState
    source: str
    details: str = ""
    raw: str = ""


class CSVEventLogger:
    """Append system events to a thread-safe CSV file."""

    legacy_fieldnames = ["timestamp", "event", "state", "source", "details"]
    fieldnames = ["timestamp", "event", "state", "source", "details", "raw"]

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
            "timestamp": timestamp.isoformat(timespec="milliseconds"),
            "event": event.event,
            "state": event.state,
            "source": event.source,
            "details": event.details,
            "raw": event.raw,
        }
        try:
            with self._lock, self.log_path.open("a", newline="", encoding="utf-8") as file:
                csv.DictWriter(file, fieldnames=self.fieldnames).writerow(row)
        except OSError as exc:
            raise RuntimeError(f"Failed to write event log {self.log_path}: {exc}") from exc

    def _ensure_header(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            existing_header = self._read_header()
            if existing_header == self.fieldnames:
                return
            if existing_header == self.legacy_fieldnames:
                self._migrate_legacy_log()
                return
            raise RuntimeError(
                f"Unsupported CSV header in {self.log_path}: {existing_header}"
            )
        try:
            with self.log_path.open("w", newline="", encoding="utf-8") as file:
                csv.DictWriter(file, fieldnames=self.fieldnames).writeheader()
        except OSError as exc:
            raise RuntimeError(f"Failed to create event log {self.log_path}: {exc}") from exc

    def _read_header(self) -> list[str]:
        try:
            with self.log_path.open("r", newline="", encoding="utf-8") as file:
                return next(csv.reader(file), [])
        except OSError as exc:
            raise RuntimeError(f"Failed to read event log {self.log_path}: {exc}") from exc

    def _migrate_legacy_log(self) -> None:
        temp_path = self.log_path.with_suffix(f"{self.log_path.suffix}.tmp")
        try:
            with self.log_path.open("r", newline="", encoding="utf-8") as source_file:
                rows = list(csv.DictReader(source_file))

            with temp_path.open("w", newline="", encoding="utf-8") as target_file:
                writer = csv.DictWriter(target_file, fieldnames=self.fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({**row, "raw": ""})

            temp_path.replace(self.log_path)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to migrate event log {self.log_path}: {exc}"
            ) from exc
