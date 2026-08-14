"""JSON messages exchanged between Python and StickS3."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, cast


DeviceState = Literal[
    "DISCONNECTED",
    "NORMAL",
    "OBSERVING",
    "SUSPECTED_FALL",
    "CONFIRMED_FALL",
    "CANCELLED",
]
DEVICE_STATES: set[str] = {
    "DISCONNECTED",
    "NORMAL",
    "OBSERVING",
    "SUSPECTED_FALL",
    "CONFIRMED_FALL",
    "CANCELLED",
}
DeviceEvent = Literal["ALARM_CANCELLED"]


class DeviceProtocolError(ValueError):
    """Raised when a device message doesn't match the shared JSON protocol."""


def serialize_state_message(state: DeviceState, timestamp: datetime) -> str:
    """Serialize one Python-to-device state update."""

    normalized_timestamp = timestamp if timestamp.tzinfo else timestamp.astimezone()
    return json.dumps(
        {
            "type": "state",
            "state": state,
            "timestamp": normalized_timestamp.isoformat(timespec="seconds"),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def parse_device_event(message: str | bytes) -> DeviceEvent:
    """Validate one StickS3-to-Python event message."""

    try:
        payload = json.loads(message)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DeviceProtocolError("message is not valid JSON") from exc

    if not isinstance(payload, dict) or payload.get("type") != "event":
        raise DeviceProtocolError("message type must be 'event'")
    if payload.get("event") != "ALARM_CANCELLED":
        raise DeviceProtocolError("unsupported device event")
    return cast(DeviceEvent, payload["event"])
