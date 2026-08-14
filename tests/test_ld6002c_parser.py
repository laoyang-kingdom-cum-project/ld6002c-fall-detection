from __future__ import annotations

from datetime import datetime
from functools import reduce
from operator import xor

import pytest

from ld6002c_fall.ld6002c_parser import (
    FALL_STATUS_TYPE,
    HUMAN_STATUS_TYPE,
    LD6002CParser,
    LD6002CProtocolError,
)


NOW = datetime(2026, 8, 12, 12, 0, 0)


def make_frame(frame_id: int, message_type: int, data: bytes) -> bytes:
    header = (
        bytes([0x01])
        + frame_id.to_bytes(2, byteorder="big")
        + len(data).to_bytes(2, byteorder="big")
        + message_type.to_bytes(2, byteorder="big")
    )
    return header + bytes([checksum(header)]) + data + bytes([checksum(data)])


def checksum(data: bytes) -> int:
    return (~reduce(xor, data, 0)) & 0xFF


def test_parser_combines_official_fall_and_human_status_reports() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    fall = bytes.fromhex("01 00 00 00 01 0e 02 f3 01 fe")
    human = bytes.fromhex("01 00 01 00 01 0f 09 f8 01 fe")

    assert parser.feed(fall[:4]) is None
    assert parser.feed(fall[4:]) is None

    result = parser.feed(human)

    assert result is not None
    assert result.timestamp == NOW
    assert result.human_present is True
    assert result.fall_detected is True
    assert result.motion_state == "unknown"
    assert result.raw == human.hex(" ")


def test_parser_resynchronizes_after_invalid_checksum() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    invalid = bytearray(make_frame(1, FALL_STATUS_TYPE, b"\x01"))
    invalid[7] ^= 0xFF
    fall = make_frame(2, FALL_STATUS_TYPE, b"\x00")
    human = make_frame(3, HUMAN_STATUS_TYPE, b"\x01")

    result = parser.feed(b"noise" + bytes(invalid) + fall + human)

    assert result is not None
    assert result.human_present is True
    assert result.fall_detected is False


def test_parse_frame_rejects_invalid_status_value() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    frame = make_frame(1, FALL_STATUS_TYPE, b"\x02")

    with pytest.raises(LD6002CProtocolError, match="invalid value"):
        parser.parse_frame(frame)


def test_feed_skips_invalid_status_value() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    invalid = make_frame(1, FALL_STATUS_TYPE, b"\x02")
    fall = make_frame(2, FALL_STATUS_TYPE, b"\x00")
    human = make_frame(3, HUMAN_STATUS_TYPE, b"\x01")

    result = parser.feed(invalid + fall + human)

    assert result is not None
    assert result.human_present is True
    assert result.fall_detected is False


def test_reset_clears_buffer_and_previous_status() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    fall = make_frame(1, FALL_STATUS_TYPE, b"\x01")
    human = make_frame(2, HUMAN_STATUS_TYPE, b"\x01")

    assert parser.feed(fall) is None
    parser.reset()
    assert parser.buffer == bytearray()
    assert parser.feed(human) is None
