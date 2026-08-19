"""CSV logging for normalized radar frames and system states."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .ai.models import FallAIResult
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
    pre_ai_fieldnames = [
        "timestamp",
        "source",
        "human_present",
        "fall_detected",
        "motion_state",
        "system_state",
        "raw",
    ]
    pre_cache_fieldnames = [
        *pre_ai_fieldnames,
        "radar_is_fall",
        "ai_result",
        "ai_label",
        "ai_status",
        "ai_success",
        "ai_model",
        "ai_inference_ms",
        "ai_message",
        "final_result",
    ]
    pre_monitor_fieldnames = [
        *pre_ai_fieldnames,
        "radar_is_fall",
        "ai_result",
        "ai_label",
        "ai_status",
        "ai_success",
        "ai_cached",
        "ai_model",
        "ai_inference_ms",
        "ai_message",
        "final_result",
    ]
    pre_pointcloud_fieldnames = [
        *pre_monitor_fieldnames,
        "device_state",
        "ai_work_state",
        "ai_trigger",
    ]
    fieldnames = [*pre_pointcloud_fieldnames, "point_count", "radar_points"]

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def log(
        self,
        frame: RadarFrame,
        system_state: str,
        source: str,
        ai_result: FallAIResult,
        device_state: str = "DISCONNECTED",
        ai_work_state: str = "IDLE",
        ai_trigger: str = "cached",
    ) -> None:
        """Write one processed frame to disk."""

        row = {
            "timestamp": frame.timestamp.isoformat(timespec="milliseconds"),
            "source": source,
            "human_present": frame.human_present,
            "fall_detected": frame.fall_detected,
            "motion_state": frame.motion_state,
            "system_state": system_state,
            "raw": frame.raw,
            "radar_is_fall": int(frame.fall_detected),
            "ai_result": ai_result.result,
            "ai_label": ai_result.label,
            "ai_status": self._ai_status(ai_result),
            "ai_success": ai_result.success,
            "ai_cached": ai_result.cached,
            "ai_model": ai_result.model,
            "ai_inference_ms": round(ai_result.inference_ms, 1),
            "ai_message": ai_result.message,
            "final_result": ai_result.result,
            "device_state": device_state,
            "ai_work_state": ai_work_state,
            "ai_trigger": ai_trigger,
            "point_count": len(frame.points),
            "radar_points": json.dumps(
                [
                    {
                        "cluster_id": point.cluster_id,
                        "x": round(point.x, 4),
                        "y": round(point.y, 4),
                        "z": round(point.z, 4),
                        "speed": round(point.speed, 4),
                    }
                    for point in frame.points
                ],
                ensure_ascii=True,
                separators=(",", ":"),
            ),
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
            if existing_header in (
                self.legacy_fieldnames,
                self.pre_ai_fieldnames,
                self.pre_cache_fieldnames,
                self.pre_monitor_fieldnames,
                self.pre_pointcloud_fieldnames,
            ):
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
                previous_ai_input: str | int | None = None
                for row in rows:
                    radar_is_fall = self._parse_bool(row.get("fall_detected", ""))
                    has_ai_data = bool(row.get("ai_result", "")) or row.get(
                        "ai_result"
                    ) == "0"
                    ai_input = row.get("radar_is_fall", radar_is_fall)
                    ai_cached = row.get("ai_cached")
                    if ai_cached is None:
                        ai_cached = has_ai_data and ai_input == previous_ai_input
                    writer.writerow(
                        {
                            "timestamp": row.get("timestamp", ""),
                            "source": row.get("source", "")
                            or self._infer_source(row.get("raw", "")),
                            "human_present": row.get("human_present", ""),
                            "fall_detected": row.get("fall_detected", ""),
                            "motion_state": row.get("motion_state", ""),
                            "system_state": row.get("system_state", ""),
                            "raw": row.get("raw", ""),
                            "radar_is_fall": ai_input,
                            "ai_result": row.get("ai_result", radar_is_fall),
                            "ai_label": row.get("ai_label", "")
                            or ("FALL" if radar_is_fall else "NORMAL"),
                            "ai_status": row.get("ai_status", "")
                            or ("AI_SUCCESS" if has_ai_data else "AI_LEGACY"),
                            "ai_success": row.get("ai_success", "")
                            if has_ai_data
                            else False,
                            "ai_cached": ai_cached,
                            "ai_model": row.get("ai_model", "")
                            or ("unknown" if has_ai_data else "legacy"),
                            "ai_inference_ms": row.get("ai_inference_ms", 0.0),
                            "ai_message": row.get("ai_message", "")
                            or (
                                ""
                                if has_ai_data
                                else "历史日志，未经过 AI 判断。"
                            ),
                            "final_result": row.get("final_result", radar_is_fall),
                            "device_state": row.get("device_state", "")
                            or self._infer_device_state(
                                row.get("system_state", ""),
                                row.get("human_present", ""),
                            ),
                            "ai_work_state": row.get("ai_work_state", "")
                            or self._infer_ai_work_state(
                                row.get("ai_status", ""),
                                row.get("ai_result", radar_is_fall),
                            ),
                            "ai_trigger": row.get("ai_trigger", "") or "legacy",
                            "point_count": row.get("point_count", 0),
                            "radar_points": row.get("radar_points", "") or "[]",
                        }
                    )
                    previous_ai_input = ai_input

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

    @staticmethod
    def _parse_bool(value: object) -> int:
        return int(str(value).strip().lower() in {"true", "1", "yes"})

    @staticmethod
    def _ai_status(result: FallAIResult) -> str:
        if result.success:
            return "AI_SUCCESS"
        if result.model == "disabled":
            return "AI_DISABLED"
        return "AI_FALLBACK"

    @classmethod
    def _infer_device_state(cls, system_state: str, human_present: object) -> str:
        states = {
            "正常有人": "NORMAL",
            "观察中": "OBSERVING",
            "疑似跌倒": "SUSPECTED_FALL",
            "确认跌倒": "CONFIRMED_FALL",
        }
        if system_state == "无人" or not cls._parse_bool(human_present):
            return "NO_PERSON"
        return states.get(system_state, "DISCONNECTED")

    @classmethod
    def _infer_ai_work_state(cls, status: str, result: object) -> str:
        if status == "AI_DISABLED" or status == "AI_LEGACY" or not status:
            return "IDLE"
        if status == "AI_FALLBACK":
            return "FALLBACK"
        if cls._parse_bool(result):
            return "FALL_DETECTED"
        return "MONITORING"
