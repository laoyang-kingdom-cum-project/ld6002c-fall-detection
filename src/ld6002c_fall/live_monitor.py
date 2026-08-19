"""Pure data model used by the Streamlit AI Live Monitor."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Mapping


Row = Mapping[str, object]


@dataclass(frozen=True)
class MonitorSnapshot:
    radar_status: str
    ollama_status: str
    ai_model: str
    sticks3_status: str
    current_status: str
    source: str
    ai_work_state: str
    human_present: bool
    fall_detected: bool
    motion_state: str
    last_update: str


@dataclass(frozen=True)
class AIChatEntry:
    timestamp: str
    is_fall: int
    result: int | None
    status: str
    model: str
    message: str
    trigger: str
    inference_ms: float | None = None
    occurrences: int = 1


@dataclass(frozen=True)
class SensorStreamEntry:
    timestamp: str
    category: str
    text: str
    raw: str


@dataclass(frozen=True)
class PointHistoryEntry:
    """One point prepared for the dashboard's synchronized projections."""

    timestamp: str
    source: str
    cluster_id: int
    x: float
    y: float
    z: float
    speed: float
    is_current: bool
    is_latest_cloud: bool


@dataclass(frozen=True)
class AxisHistoryEntry:
    """Centroid of one point-cloud frame for the XYZ timeline."""

    timestamp: str
    source: str
    x: float
    y: float
    z: float
    point_count: int
    mean_speed: float


def build_monitor_snapshot(
    frames: Iterable[Row],
    events: Iterable[Row],
    *,
    now: datetime | None = None,
    stale_seconds: float = 15.0,
    ai_event_stale_seconds: float = 30.0,
) -> MonitorSnapshot:
    """Build current device and AI status from persisted logs."""

    frame_rows = list(frames)
    event_rows = list(events)
    latest = frame_rows[-1] if frame_rows else {}
    latest_timestamp = _text(latest.get("timestamp"))
    timestamp = _parse_timestamp(latest_timestamp)
    current_time = now or datetime.now().astimezone()
    is_fresh = timestamp is not None and abs((current_time - timestamp).total_seconds()) <= stale_seconds

    ai_status = _text(latest.get("ai_status"))
    work_state = _text(latest.get("ai_work_state")) or _work_state(ai_status, latest)
    analyzing = _has_pending_ai_request(
        event_rows,
        now=current_time,
        stale_seconds=ai_event_stale_seconds,
    )
    latest_event_state = _latest_ai_event_state(
        event_rows,
        now=current_time,
        stale_seconds=ai_event_stale_seconds,
    )
    if analyzing:
        work_state = "ANALYZING"
    elif latest_event_state in {"ERROR", "FALLBACK"}:
        work_state = latest_event_state

    human_present = _as_bool(latest.get("human_present"))
    fall_detected = _as_bool(latest.get("final_result", latest.get("fall_detected")))
    device_state = _text(latest.get("device_state"))
    current_status = _current_status(device_state, human_present) if is_fresh else "DISCONNECTED"

    return MonitorSnapshot(
        radar_status="CONNECTED" if frame_rows and is_fresh else "DISCONNECTED",
        ollama_status=(
            _ollama_status(ai_status, work_state) if is_fresh else "UNKNOWN"
        ),
        ai_model=_text(latest.get("ai_model")) or "unknown",
        sticks3_status=_sticks3_status(event_rows),
        current_status=current_status,
        source=_source_label(latest),
        ai_work_state=work_state or "IDLE",
        human_present=human_present,
        fall_detected=fall_detected,
        motion_state=_text(latest.get("motion_state")) or "unknown",
        last_update=latest_timestamp or "--",
    )


def build_ai_chat(events: Iterable[Row], *, max_items: int = 100) -> list[AIChatEntry]:
    """Pair real AI requests and outcomes, merging repeated normal checks."""

    entries: list[AIChatEntry] = []
    pending: dict[str, object] | None = None
    pending_timestamp = ""
    error_message = ""

    for event in events:
        name = _text(event.get("event"))
        details = _details(event.get("details"))
        timestamp = _text(event.get("timestamp"))
        if name in {"ALARM_TRIGGERED", "ALARM_CANCELLED"}:
            entries.append(
                AIChatEntry(
                    timestamp=timestamp,
                    is_fall=1,
                    result=1 if name == "ALARM_TRIGGERED" else None,
                    status=name,
                    model="alarm-output",
                    message=(
                        "Python 已触发电脑本地语音报警。"
                        if name == "ALARM_TRIGGERED"
                        else "本次报警已取消。"
                    ),
                    trigger="system_event",
                )
            )
            continue
        if name == "AI_REQUEST":
            if pending is not None:
                entries.append(_pending_entry(pending_timestamp, pending))
            pending = details
            pending_timestamp = timestamp
            error_message = ""
            continue
        if name == "AI_ERROR":
            error_message = _text(details.get("message"))
            continue
        if name not in {"AI_RESPONSE", "AI_FALLBACK"}:
            continue

        request = pending or {}
        is_fall = _as_int(request.get("is_fall", details.get("result", 0)))
        result = _as_int(details.get("result", is_fall))
        trigger = _text(details.get("trigger", request.get("trigger"))) or "unknown"
        status = "FALLBACK" if name == "AI_FALLBACK" else (
            "FALL_DETECTED" if result == 1 else "COMPLETED"
        )
        message = _text(details.get("message")) or error_message or "AI 已返回判断结果。"
        entry = AIChatEntry(
            timestamp=timestamp,
            is_fall=is_fall,
            result=result,
            status=status,
            model=_text(details.get("model", request.get("model"))) or "fallback",
            message=message,
            trigger=trigger,
            inference_ms=_as_float(details.get("inference_ms")),
        )
        if (
            trigger == "periodic"
            and result == 0
            and entries
            and entries[-1].trigger == "periodic"
            and entries[-1].result == 0
            and entries[-1].status == status
        ):
            previous = entries[-1]
            entries[-1] = replace(
                entry,
                occurrences=previous.occurrences + 1,
            )
        else:
            entries.append(entry)
        pending = None
        error_message = ""

    if pending is not None:
        entries.append(_pending_entry(pending_timestamp, pending))
    return entries[-max_items:]


def build_sensor_stream(
    frames: Iterable[Row],
    events: Iterable[Row],
    *,
    max_items: int = 100,
) -> list[SensorStreamEntry]:
    """Merge persisted radar frames and important system events."""

    items: list[tuple[datetime, int, SensorStreamEntry]] = []
    for index, frame in enumerate(frames):
        timestamp = _text(frame.get("timestamp"))
        source = _source_label(frame)
        text = (
            f"{source} present={int(_as_bool(frame.get('human_present')))} "
            f"radar_fall={_as_int(frame.get('radar_is_fall', frame.get('fall_detected')))} "
            f"motion={_text(frame.get('motion_state')) or 'unknown'}"
        )
        items.append(
            (
                _parse_timestamp(timestamp) or datetime.min.astimezone(),
                index,
                SensorStreamEntry(timestamp, "RADAR", text, _text(frame.get("raw"))),
            )
        )
    offset = len(items)
    for index, event in enumerate(events):
        timestamp = _text(event.get("timestamp"))
        name = _text(event.get("event")) or "EVENT"
        details = _text(event.get("details"))
        items.append(
            (
                _parse_timestamp(timestamp) or datetime.min.astimezone(),
                offset + index,
                SensorStreamEntry(
                    timestamp,
                    name,
                    details or name,
                    _text(event.get("raw")),
                ),
            )
        )
    items.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in items[-max_items:]]


def build_point_history(
    frames: Iterable[Row],
    *,
    max_frames: int = 40,
) -> list[PointHistoryEntry]:
    """Parse persisted point JSON into a projection-friendly history."""

    rows = list(frames)
    parsed: list[tuple[int, Row, list[dict[str, object]]]] = []
    for index, row in enumerate(rows):
        points = _point_values(row.get("radar_points"))
        if points:
            parsed.append((index, row, points))

    if not parsed:
        return []

    parsed = parsed[-max_frames:]
    latest_cloud_index = parsed[-1][0]
    current_index = len(rows) - 1
    history: list[PointHistoryEntry] = []
    for index, row, points in parsed:
        for point in points:
            try:
                x = float(point["x"])
                y = float(point["y"])
                z = float(point["z"])
                speed = float(point.get("speed", 0.0))
                if not all(math.isfinite(value) for value in (x, y, z, speed)):
                    continue
                history.append(
                    PointHistoryEntry(
                        timestamp=_text(row.get("timestamp")),
                        source=_source_label(row),
                        cluster_id=int(point.get("cluster_id", 0)),
                        x=x,
                        y=y,
                        z=z,
                        speed=speed,
                        is_current=index == current_index,
                        is_latest_cloud=index == latest_cloud_index,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return history


def build_axis_history(
    points: Iterable[PointHistoryEntry],
    *,
    max_samples: int = 40,
) -> list[AxisHistoryEntry]:
    """Aggregate each point-cloud frame into an XYZ centroid sample."""

    if max_samples <= 0:
        return []

    grouped: dict[tuple[str, str], list[PointHistoryEntry]] = {}
    for point in points:
        grouped.setdefault((point.timestamp, point.source), []).append(point)

    samples: list[AxisHistoryEntry] = []
    for (timestamp, source), frame_points in grouped.items():
        count = len(frame_points)
        samples.append(
            AxisHistoryEntry(
                timestamp=timestamp,
                source=source,
                x=sum(point.x for point in frame_points) / count,
                y=sum(point.y for point in frame_points) / count,
                z=sum(point.z for point in frame_points) / count,
                point_count=count,
                mean_speed=sum(abs(point.speed) for point in frame_points) / count,
            )
        )
    return samples[-max_samples:]


def point_cloud_status(
    history: Iterable[PointHistoryEntry],
    *,
    now: datetime | None = None,
    stale_seconds: float = 5.0,
) -> str:
    """Report point-cloud freshness independently from status-frame updates."""

    entries = list(history)
    if not entries:
        return "WAITING"
    timestamp = _parse_timestamp(entries[-1].timestamp)
    if timestamp is None:
        return "STALE"
    current_time = now or datetime.now().astimezone()
    age = abs((current_time - timestamp).total_seconds())
    return "TRACKING" if age <= stale_seconds else "STALE"


def _pending_entry(timestamp: str, details: Row) -> AIChatEntry:
    return AIChatEntry(
        timestamp=timestamp,
        is_fall=_as_int(details.get("is_fall")),
        result=None,
        status="ANALYZING",
        model=_text(details.get("model")) or "unknown",
        message="正在分析最新雷达数据...",
        trigger=_text(details.get("trigger")) or "unknown",
    )


def _has_pending_ai_request(
    events: list[Row],
    *,
    now: datetime,
    stale_seconds: float,
) -> bool:
    last_request = -1
    last_completion = -1
    for index, event in enumerate(events):
        name = _text(event.get("event"))
        if name == "AI_REQUEST":
            last_request = index
        elif name in {"AI_RESPONSE", "AI_ERROR", "AI_FALLBACK"}:
            last_completion = index
    if last_request <= last_completion:
        return False
    timestamp = _parse_timestamp(_text(events[last_request].get("timestamp")))
    return (
        timestamp is not None
        and abs((now - timestamp).total_seconds()) <= stale_seconds
    )


def _latest_ai_event_state(
    events: list[Row],
    *,
    now: datetime,
    stale_seconds: float,
) -> str | None:
    for event in reversed(events):
        name = _text(event.get("event"))
        if name not in {"AI_REQUEST", "AI_ERROR", "AI_FALLBACK", "AI_RESPONSE"}:
            continue
        timestamp = _parse_timestamp(_text(event.get("timestamp")))
        if timestamp is None or abs((now - timestamp).total_seconds()) > stale_seconds:
            return None
        if name == "AI_REQUEST":
            return "ANALYZING"
        if name == "AI_ERROR":
            return "ERROR"
        if name == "AI_FALLBACK":
            return "FALLBACK"
        if name == "AI_RESPONSE":
            return "COMPLETED"
    return None


def _current_status(device_state: str, human_present: bool) -> str:
    if device_state == "OBSERVING":
        return "OBSERVING"
    if device_state in {"SUSPECTED_FALL", "CONFIRMED_FALL", "CANCELLED"}:
        return device_state
    if device_state == "DISCONNECTED":
        return "DISCONNECTED"
    if not human_present:
        return "NO_PERSON"
    return "NORMAL"


def _ollama_status(ai_status: str, work_state: str) -> str:
    if ai_status == "AI_DISABLED" or work_state == "IDLE":
        return "DISABLED"
    if ai_status == "AI_FALLBACK" or work_state in {"ERROR", "FALLBACK"}:
        return "FALLBACK"
    return "CONNECTED"


def _work_state(ai_status: str, latest: Row) -> str:
    if ai_status in {"", "AI_DISABLED", "AI_LEGACY"}:
        return "IDLE"
    if ai_status == "AI_FALLBACK":
        return "FALLBACK"
    if _as_bool(latest.get("ai_result")):
        return "FALL_DETECTED"
    return "MONITORING"


def _sticks3_status(events: list[Row]) -> str:
    status = "DISCONNECTED"
    for event in events:
        name = _text(event.get("event"))
        if name == "DEVICE_CONNECTED":
            status = "CONNECTED"
        elif name == "DEVICE_DISCONNECTED":
            status = "DISCONNECTED"
    return status


def _source_label(row: Row) -> str:
    source = _text(row.get("source")).lower()
    if source == "mock" or _text(row.get("raw")).startswith("mock:"):
        return "MOCK"
    if source == "serial":
        return "HLK-LD6002C"
    if source == "replay":
        return "REPLAY"
    return source.upper() or "UNKNOWN"


def _details(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(_text(value))
    except (json.JSONDecodeError, TypeError):
        return {"message": _text(value)}
    return parsed if isinstance(parsed, dict) else {"message": _text(value)}


def _point_values(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        parsed = value
    else:
        try:
            parsed = json.loads(_text(value) or "[]")
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(parsed, list):
        return []
    return [point for point in parsed if isinstance(point, dict)]


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text.strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"true", "1", "yes"}


def _as_int(value: object) -> int:
    return int(_as_bool(value))


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
