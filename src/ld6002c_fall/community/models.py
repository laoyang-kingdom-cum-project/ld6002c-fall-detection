"""Typed community residents, states, and audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping


CommunityStatus = Literal["NORMAL", "WARNING", "FALL", "OFFLINE", "RECOVERED"]
CommunityEventName = Literal[
    "FALL_ALERT",
    "ALERT_ACKNOWLEDGED",
    "RECOVERED",
    "DEVICE_OFFLINE",
    "DEVICE_ONLINE",
    "DEMO_INJECTED",
]

VALID_STATUSES = {"NORMAL", "WARNING", "FALL", "OFFLINE", "RECOVERED"}


def local_now() -> datetime:
    """Return one timezone-aware timestamp for persistence and display."""

    return datetime.now().astimezone()


@dataclass(frozen=True)
class Resident:
    """One monitored resident from the static community registry."""

    id: str
    building: str
    room: str
    name: str
    age: int
    sensor_binding: str | None = None

    @property
    def address(self) -> str:
        return f"{self.building}{self.room}"

    @property
    def has_live_sensor(self) -> bool:
        return bool(self.sensor_binding)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Resident":
        try:
            resident = cls(
                id=str(value["id"]).strip(),
                building=str(value["building"]).strip(),
                room=str(value["room"]).strip(),
                name=str(value["name"]).strip(),
                age=int(value["age"]),
                sensor_binding=(
                    str(value["sensor_binding"]).strip()
                    if value.get("sensor_binding")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid resident configuration: {value!r}") from exc
        if not all((resident.id, resident.building, resident.room, resident.name)):
            raise ValueError(f"Resident fields must not be empty: {value!r}")
        if resident.age <= 0:
            raise ValueError(f"Resident age must be positive: {resident.id}")
        return resident


@dataclass(frozen=True)
class ResidentState:
    """Latest community-facing state for one resident."""

    resident_id: str
    status: CommunityStatus = "NORMAL"
    radar_result: int | None = None
    ai_result: int | None = None
    ai_model: str | None = None
    ai_success: bool | None = None
    alarm_time: datetime | None = None
    handled: bool = False
    updated_at: datetime = field(default_factory=local_now)
    source: str = "INITIAL"
    demo_override: bool = False

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Unsupported community status: {self.status}")
        if self.radar_result not in (None, 0, 1):
            raise ValueError("radar_result must be None, 0, or 1")
        if self.ai_result not in (None, 0, 1):
            raise ValueError("ai_result must be None, 0, or 1")

    def to_mapping(self) -> dict[str, object]:
        return {
            "resident_id": self.resident_id,
            "status": self.status,
            "radar_result": self.radar_result,
            "ai_result": self.ai_result,
            "ai_model": self.ai_model,
            "ai_success": self.ai_success,
            "alarm_time": _format_datetime(self.alarm_time),
            "handled": self.handled,
            "updated_at": _format_datetime(self.updated_at),
            "source": self.source,
            "demo_override": self.demo_override,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        resident_id: str,
    ) -> "ResidentState":
        status = str(value.get("status", "NORMAL")).upper()
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported community status for {resident_id}: {status}")
        return cls(
            resident_id=resident_id,
            status=status,  # type: ignore[arg-type]
            radar_result=_optional_binary(value.get("radar_result")),
            ai_result=_optional_binary(value.get("ai_result")),
            ai_model=_optional_text(value.get("ai_model")),
            ai_success=_optional_bool(value.get("ai_success")),
            alarm_time=_parse_datetime(value.get("alarm_time")),
            handled=bool(value.get("handled", False)),
            updated_at=_parse_datetime(value.get("updated_at")) or local_now(),
            source=str(value.get("source") or "INITIAL"),
            demo_override=bool(value.get("demo_override", False)),
        )


@dataclass(frozen=True)
class CommunityEvent:
    """One resident-level event persisted to the community event CSV."""

    timestamp: datetime
    resident_id: str
    building: str
    room: str
    name: str
    event: CommunityEventName
    status: CommunityStatus
    source: str
    radar_result: int | None = None
    ai_result: int | None = None
    details: str = ""


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.astimezone()
    return aware.isoformat(timespec="milliseconds")


def _parse_datetime(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid persisted datetime: {value!r}") from exc
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _optional_binary(value: object) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed not in (0, 1):
        raise ValueError(f"Expected binary value, got {value!r}")
    return parsed


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
