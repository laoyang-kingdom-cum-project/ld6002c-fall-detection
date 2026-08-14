from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ld6002c_fall.device_protocol import (
    DeviceProtocolError,
    parse_device_event,
    serialize_state_message,
)


@pytest.mark.parametrize(
    "state",
    ["NORMAL", "SUSPECTED_FALL", "CONFIRMED_FALL", "CANCELLED"],
)
def test_serialize_state_message(state: str) -> None:
    timestamp = datetime(2026, 8, 14, 15, 30, tzinfo=timezone.utc)

    payload = json.loads(serialize_state_message(state, timestamp))  # type: ignore[arg-type]

    assert payload == {
        "type": "state",
        "state": state,
        "timestamp": "2026-08-14T15:30:00+00:00",
    }


def test_parse_alarm_cancelled_event() -> None:
    assert parse_device_event('{"type":"event","event":"ALARM_CANCELLED"}') == (
        "ALARM_CANCELLED"
    )


def test_reject_unknown_device_event() -> None:
    with pytest.raises(DeviceProtocolError, match="unsupported"):
        parse_device_event('{"type":"event","event":"UNKNOWN"}')
