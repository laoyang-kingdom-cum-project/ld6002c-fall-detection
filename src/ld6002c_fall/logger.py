"""CSV logging for normalized radar frames and system states."""

from __future__ import annotations

import csv
from pathlib import Path

from .radar_model import RadarFrame


class CSVFrameLogger:
    """Append each processed radar frame to a CSV file."""

    legacy_fieldnames = [
        "timestamp",
        "human_present",
        "fall_detected",
        "motion_state",
        "system_state",
        "raw",
    ]
    fieldnames = [
        "timestamp",
        "source",
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

    def log(self, frame: RadarFrame, system_state: str, source: str) -> None:
        """Write one processed frame to disk."""

        row = {
            "timestamp": frame.timestamp.isoformat(timespec="seconds"),
            "source": source,
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
                writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                writer.writeheader()
        except OSError as exc:
            raise RuntimeError(f"Failed to create CSV log {self.log_path}: {exc}") from exc

    def _read_header(self) -> list[str]:
        try:
            with self.log_path.open("r", newline="", encoding="utf-8") as file:
                reader = csv.reader(file)
                return next(reader, [])
        except OSError as exc:
            raise RuntimeError(f"Failed to read CSV log {self.log_path}: {exc}") from exc

    def _migrate_legacy_log(self) -> None:
        temp_path = self.log_path.with_suffix(f"{self.log_path.suffix}.tmp")
        try:
            with self.log_path.open("r", newline="", encoding="utf-8") as source_file:
                reader = csv.DictReader(source_file)
                rows = list(reader)

            with temp_path.open("w", newline="", encoding="utf-8") as target_file:
                writer = csv.DictWriter(target_file, fieldnames=self.fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            "timestamp": row.get("timestamp", ""),
                            "source": self._infer_source(row.get("raw", "")),
                            "human_present": row.get("human_present", ""),
                            "fall_detected": row.get("fall_detected", ""),
                            "motion_state": row.get("motion_state", ""),
                            "system_state": row.get("system_state", ""),
                            "raw": row.get("raw", ""),
                        }
                    )

            temp_path.replace(self.log_path)
        except OSError as exc:
            raise RuntimeError(f"Failed to migrate CSV log {self.log_path}: {exc}") from exc

    @staticmethod
    def _infer_source(raw: str) -> str:
        if raw.startswith("mock:"):
            return "mock"
        if raw.strip():
            return "serial_or_replay"
        return "unknown"
