"""Per-resident simulated telemetry for the classroom community demo."""

from __future__ import annotations

import csv
import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..ai import FallAIResult
from ..device_protocol import DeviceState
from ..event_logger import CSVEventLogger, EventName, SystemEvent
from ..logger import CSVFrameLogger
from ..config import DEFAULT_COMMUNITY_TELEMETRY_MAX_FRAMES
from ..mock_reader import MockRadarStatus, build_mock_radar_frame
from ..radar_model import RadarFrame


SIMULATED_SOURCE = "community_demo"
SIMULATED_SOURCE_LABEL = "SIMULATED RADAR DATA · CLASSROOM DEMO"


class CommunityTelemetryStore:
    """Persist bounded demo frames and events for each community resident."""

    fieldnames = ["resident_id", *CSVFrameLogger.fieldnames]

    def __init__(
        self,
        directory: str | Path,
        *,
        max_frames: int = DEFAULT_COMMUNITY_TELEMETRY_MAX_FRAMES,
    ) -> None:
        if max_frames < 1:
            raise ValueError("max_frames must be positive")
        self.directory = Path(directory)
        self.max_frames = max_frames
        self.directory.mkdir(parents=True, exist_ok=True)

    def frame_path(self, resident_id: str) -> Path:
        return self.directory / f"{_safe_id(resident_id)}.csv"

    def event_path(self, resident_id: str) -> Path:
        return self.directory / f"{_safe_id(resident_id)}.events.csv"

    def has_frames(self, resident_id: str) -> bool:
        path = self.frame_path(resident_id)
        return path.is_file() and path.stat().st_size > 0

    def write_scenario(
        self,
        resident_id: str,
        status: MockRadarStatus,
        ai_result: FallAIResult,
        *,
        timestamp: datetime,
        frame_count: int = 30,
        interval_seconds: float = 0.5,
    ) -> RadarFrame:
        """Atomically replace a resident's history with a fresh demo sequence."""

        if frame_count < 1:
            raise ValueError("frame_count must be positive")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        start = timestamp - timedelta(seconds=(frame_count - 1) * interval_seconds)
        rows: list[dict[str, object]] = []
        frames: list[RadarFrame] = []
        for index in range(frame_count):
            elapsed = index * interval_seconds
            frame = build_mock_radar_frame(
                status,
                elapsed,
                timestamp=start + timedelta(seconds=elapsed),
                resident_id=resident_id,
            )
            frames.append(frame)
            rows.append(_frame_row(resident_id, frame, status, ai_result))
        self._write_rows(self.frame_path(resident_id), rows)
        return frames[-1]

    def write_offline(
        self,
        resident_id: str,
        *,
        timestamp: datetime,
    ) -> RadarFrame:
        """Write a disconnected status frame without inventing point-cloud data."""

        frame = RadarFrame(
            timestamp=timestamp,
            human_present=False,
            fall_detected=False,
            motion_state="unknown",
            raw=f"community-demo:resident={resident_id};status=OFFLINE",
            points=(),
        )
        fallback = FallAIResult(
            result=0,
            label="NORMAL",
            message="演示设备已离线，未执行 AI 判断。",
            model="not-requested",
            inference_ms=0.0,
            success=False,
        )
        row = _frame_row(resident_id, frame, "NORMAL", fallback)
        row.update(
            {
                "device_state": "DISCONNECTED",
                "ai_status": "AI_DISABLED",
                "ai_work_state": "IDLE",
                "point_count": 0,
                "radar_points": "[]",
            }
        )
        self._append_row(self.frame_path(resident_id), row)
        return frame

    def append_frame(
        self,
        resident_id: str,
        frame: RadarFrame,
        status: MockRadarStatus,
        ai_result: FallAIResult,
    ) -> None:
        """Atomically append one frame while retaining only the rolling window."""

        self._append_row(
            self.frame_path(resident_id),
            _frame_row(resident_id, frame, status, ai_result),
        )

    def log_event(
        self,
        resident_id: str,
        event: EventName,
        *,
        timestamp: datetime,
        state: DeviceState,
        details: str,
        raw: str = "",
    ) -> None:
        CSVEventLogger(self.event_path(resident_id)).log(
            SystemEvent(
                timestamp=timestamp,
                event=event,
                state=state,
                source=SIMULATED_SOURCE,
                details=details,
                raw=raw,
            )
        )

    def clear(self) -> None:
        """Remove only generated community-demo telemetry and event files."""

        for path in self.directory.glob("*.csv"):
            path.unlink(missing_ok=True)

    def _write_rows(self, path: Path, rows: list[dict[str, object]]) -> None:
        with _file_lock(path):
            self._write_rows_unlocked(path, rows)

    def _append_row(self, path: Path, row: dict[str, object]) -> None:
        with _file_lock(path):
            rows: list[dict[str, object]] = []
            if path.exists() and path.stat().st_size > 0:
                try:
                    with path.open(newline="", encoding="utf-8") as file:
                        rows = list(csv.DictReader(file))
                except (OSError, csv.Error) as exc:
                    raise RuntimeError(
                        f"Failed to read community telemetry {path}: {exc}"
                    ) from exc
            rows.append(row)
            self._write_rows_unlocked(path, rows[-self.max_frames :])

    def _write_rows_unlocked(
        self,
        path: Path,
        rows: list[dict[str, object]],
    ) -> None:
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise RuntimeError(f"Failed to write community telemetry {path}: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)


class _file_lock:
    """Small cross-process lock used by runtime writers and dashboard readers."""

    def __init__(self, target: Path, timeout: float = 3.0) -> None:
        self.lock_path = target.with_suffix(f"{target.suffix}.lock")
        self.timeout = timeout
        self.descriptor: int | None = None

    def __enter__(self) -> None:
        import time

        deadline = time.monotonic() + self.timeout
        while self.descriptor is None:
            try:
                self.descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self.descriptor, str(os.getpid()).encode("ascii"))
            except FileExistsError:
                try:
                    if time.time() - self.lock_path.stat().st_mtime > 30:
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Timed out waiting for telemetry lock {self.lock_path}"
                    )
                time.sleep(0.02)

    def __exit__(self, *_args: object) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
        self.lock_path.unlink(missing_ok=True)


def _frame_row(
    resident_id: str,
    frame: RadarFrame,
    status: MockRadarStatus,
    ai_result: FallAIResult,
) -> dict[str, object]:
    system_state = {
        "NORMAL": "正常有人",
        "WARNING": "疑似跌倒",
        "FALL": "确认跌倒",
    }[status]
    device_state = {
        "NORMAL": "NORMAL",
        "WARNING": "SUSPECTED_FALL",
        "FALL": "CONFIRMED_FALL",
    }[status]
    final_result = int(status == "FALL" and ai_result.result == 1)
    ai_status = (
        "AI_SUCCESS"
        if ai_result.success
        else ("AI_DISABLED" if ai_result.model in {"disabled", "not-requested"} else "AI_FALLBACK")
    )
    ai_work_state = (
        "FALL_DETECTED"
        if final_result
        else ("FALLBACK" if ai_status == "AI_FALLBACK" else "MONITORING")
    )
    return {
        "resident_id": resident_id,
        "timestamp": frame.timestamp.isoformat(timespec="milliseconds"),
        "source": SIMULATED_SOURCE,
        "human_present": frame.human_present,
        "fall_detected": frame.fall_detected,
        "motion_state": frame.motion_state,
        "system_state": system_state,
        "raw": frame.raw,
        "radar_is_fall": int(frame.fall_detected),
        "ai_result": ai_result.result,
        "ai_label": ai_result.label,
        "ai_status": ai_status,
        "ai_success": ai_result.success,
        "ai_cached": False,
        "ai_model": ai_result.model,
        "ai_inference_ms": round(ai_result.inference_ms, 1),
        "ai_message": ai_result.message,
        "final_result": final_result,
        "device_state": device_state,
        "ai_work_state": ai_work_state,
        "ai_trigger": "demo_control",
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


def _safe_id(resident_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", resident_id):
        raise ValueError(f"Invalid resident id for telemetry: {resident_id}")
    return resident_id
