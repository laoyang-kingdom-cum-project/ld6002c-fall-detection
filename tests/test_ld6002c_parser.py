from __future__ import annotations

from datetime import datetime
from functools import reduce
from operator import xor
import struct

import pytest

from ld6002c_fall.ld6002c_parser import (
    FALL_STATUS_TYPE,
    HUMAN_STATUS_TYPE,
    LD6002CParser,
    LD6002CProtocolError,
    POINT_CLOUD_TYPE,
    build_user_log_command,
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


def test_parser_reads_official_3d_point_cloud_layout() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    fall = make_frame(1, FALL_STATUS_TYPE, b"\x00")
    human = make_frame(2, HUMAN_STATUS_TYPE, b"\x01")
    payload = struct.pack(
        "<iiffffiffff",
        2,
        7,
        -0.25,
        1.2,
        0.85,
        -0.1,
        8,
        0.4,
        1.35,
        0.3,
        0.05,
    )
    point_cloud = make_frame(3, POINT_CLOUD_TYPE, payload)

    assert parser.feed(fall) is None
    assert parser.feed(human) is not None
    result = parser.feed(point_cloud)

    assert result is not None
    assert len(result.points) == 2
    assert result.points[0].cluster_id == 7
    assert result.points[0].x == pytest.approx(-0.25)
    assert result.points[0].y == pytest.approx(1.2)
    assert result.points[0].z == pytest.approx(0.85)
    assert result.points[0].speed == pytest.approx(-0.1)


def test_parser_rejects_point_cloud_length_mismatch() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    payload = struct.pack("<iiffff", 2, 1, 0.0, 1.0, 2.0, 0.1)
    frame = make_frame(1, POINT_CLOUD_TYPE, payload)

    with pytest.raises(LD6002CProtocolError, match="does not match target_num"):
        parser.parse_frame(frame)


def test_status_frames_do_not_repeat_the_last_point_cloud() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    fall = make_frame(1, FALL_STATUS_TYPE, b"\x00")
    human = make_frame(2, HUMAN_STATUS_TYPE, b"\x01")
    point_cloud = make_frame(
        3,
        POINT_CLOUD_TYPE,
        struct.pack("<iiffff", 1, 5, 0.1, 1.2, 1.7, 0.2),
    )

    assert parser.feed(fall) is None
    assert parser.feed(human) is not None
    assert parser.feed(point_cloud).points
    status = parser.feed(fall)

    assert status is not None
    assert status.points == ()


def test_parser_rejects_non_finite_point_coordinates() -> None:
    parser = LD6002CParser(clock=lambda: NOW)
    frame = make_frame(
        1,
        POINT_CLOUD_TYPE,
        struct.pack("<iiffff", 1, 5, float("nan"), 1.2, 1.7, 0.2),
    )

    with pytest.raises(LD6002CProtocolError, match="must be finite"):
        parser.parse_frame(frame)


def test_user_log_enable_command_matches_official_example() -> None:
    command = build_user_log_command(True)

    assert command == bytes.fromhex(
        "01 00 00 00 04 01 0e f5 01 00 00 00 fe"
    )


def test_user_log_disable_command_uses_little_endian_uint32_zero() -> None:
    command = build_user_log_command(False)

    assert command == bytes.fromhex(
        "01 00 00 00 04 01 0e f5 00 00 00 00 ff"
    )
