"""CSV logging for normalized radar frames and system states."""

from __future__ import annotations

import csv
from pathlib import Path

from .radar_model import RadarFrame


class CSVFrameLogger:
    """Append each processed radar frame to a CSV file."""

    fieldnames = [
        "timestamp",
        "human_present",
        "fall_detected",
        "motion_state",
        "system_state",
        "raw",
    ]

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def log(self, frame: RadarFrame, system_state: str) -> None:
        """Write one processed frame to disk."""

        row = {
            "timestamp": frame.timestamp.isoformat(timespec="seconds"),
            "human_present": frame.human_present,
            "fall_detected": frame.fall_detected,
            "motion_state": frame.motion_state,
            "system_state": system_state,
            "raw": frame.raw,
        }

        try:
            with self.log_path.open("a", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                writer.writerow(row)
        except OSError as exc:
            raise RuntimeError(f"Failed to write CSV log {self.log_path}: {exc}") from exc

    def _ensure_header(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            return

        try:
            with self.log_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                writer.writeheader()
        except OSError as exc:
            raise RuntimeError(f"Failed to create CSV log {self.log_path}: {exc}") from exc
