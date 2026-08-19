"""Incremental parser for the official LD6002C TinyFrame protocol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import reduce
import math
from operator import xor
import struct

from .radar_model import RadarFrame, RadarPoint


SOF = 0x01
HEADER_SIZE = 8
MAX_DATA_LENGTH = 1024
FALL_STATUS_TYPE = 0x0E02
HUMAN_STATUS_TYPE = 0x0F09
POINT_CLOUD_TYPE = 0x0A08
USER_LOG_TYPE = 0x010E
NORMALIZED_MESSAGE_TYPES = {FALL_STATUS_TYPE, HUMAN_STATUS_TYPE, POINT_CLOUD_TYPE}
POINT_RECORD_SIZE = 20


class LD6002CProtocolError(ValueError):
    """Raised when a complete frame violates the official protocol."""


class LD6002CParser:
    """Parse LD6002C bytes and normalize fall and presence reports.

    The radar sends TinyFrame messages. Header fields use big-endian byte
    order, while payload fields use little-endian byte order. This parser
    normalizes the two one-byte status reports and the documented 0x0A08 3D
    point-cloud report. Other validated message types are safely skipped.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.buffer = bytearray()
        self._clock = clock or datetime.now
        self._human_present = False
        self._fall_detected = False
        self._human_status_seen = False
        self._fall_status_seen = False

    def feed(self, data: bytes) -> RadarFrame | None:
        """Add bytes and return the next complete normalized status frame.

        Bytes before a valid SOF or frames with invalid checksums are discarded
        one byte at a time so that the parser can synchronize with the next
        valid frame. Passing ``b""`` drains a complete frame already buffered.
        """

        self.buffer.extend(data)

        while True:
            frame = self._extract_frame()
            if frame is None:
                return None

            message_type = int.from_bytes(frame[5:7], byteorder="big")
            if message_type not in NORMALIZED_MESSAGE_TYPES:
                continue

            try:
                normalized = self.parse_frame(frame)
            except LD6002CProtocolError:
                continue
            if self._human_status_seen and self._fall_status_seen:
                return normalized

    def reset(self) -> None:
        """Discard buffered bytes and previously observed status values."""

        self.buffer.clear()
        self._human_present = False
        self._fall_detected = False
        self._human_status_seen = False
        self._fall_status_seen = False

    def parse_frame(self, frame: bytes) -> RadarFrame:
        """Convert one validated status or point-cloud report into a frame."""

        data_length, message_type, data = self._validate_frame(frame)
        if message_type == POINT_CLOUD_TYPE:
            return self._normalized_frame(frame, points=self._parse_point_cloud(data))

        if message_type not in {FALL_STATUS_TYPE, HUMAN_STATUS_TYPE}:
            raise LD6002CProtocolError(
                f"message type 0x{message_type:04X} is not normalized"
            )
        if data_length != 1:
            raise LD6002CProtocolError(
                f"status message 0x{message_type:04X} must contain one data byte"
            )

        status = data[0]
        if status not in (0, 1):
            raise LD6002CProtocolError(
                f"status message 0x{message_type:04X} has invalid value {status}"
            )

        if message_type == FALL_STATUS_TYPE:
            self._fall_detected = bool(status)
            self._fall_status_seen = True
        elif message_type == HUMAN_STATUS_TYPE:
            self._human_present = bool(status)
            self._human_status_seen = True
        return self._normalized_frame(frame)

    def _normalized_frame(
        self,
        frame: bytes,
        *,
        points: tuple[RadarPoint, ...] = (),
    ) -> RadarFrame:
        return RadarFrame(
            timestamp=self._clock(),
            human_present=self._human_present,
            fall_detected=self._fall_detected,
            motion_state="unknown",
            raw=frame.hex(" "),
            points=points,
        )

    @staticmethod
    def _parse_point_cloud(data: bytes) -> tuple[RadarPoint, ...]:
        """Parse the official target-count plus repeated point layout."""

        if len(data) < 4:
            raise LD6002CProtocolError("point-cloud message is missing target_num")

        target_count = struct.unpack_from("<i", data)[0]
        if target_count < 0:
            raise LD6002CProtocolError("point-cloud target_num cannot be negative")

        expected_length = 4 + target_count * POINT_RECORD_SIZE
        if len(data) != expected_length:
            raise LD6002CProtocolError(
                "point-cloud payload length does not match target_num: "
                f"got {len(data)}, expected {expected_length}"
            )

        points = []
        for index in range(target_count):
            offset = 4 + index * POINT_RECORD_SIZE
            cluster_id, x, y, z, speed = struct.unpack_from("<iffff", data, offset)
            if not all(math.isfinite(value) for value in (x, y, z, speed)):
                raise LD6002CProtocolError("point-cloud coordinates must be finite")
            points.append(RadarPoint(cluster_id, x, y, z, speed))
        return tuple(points)

    def _extract_frame(self) -> bytes | None:
        while self.buffer:
            sof_index = self.buffer.find(bytes([SOF]))
            if sof_index < 0:
                self.buffer.clear()
                return None
            if sof_index > 0:
                del self.buffer[:sof_index]

            if len(self.buffer) < HEADER_SIZE:
                return None

            data_length = int.from_bytes(self.buffer[3:5], byteorder="big")
            if data_length > MAX_DATA_LENGTH:
                del self.buffer[0]
                continue

            frame_length = HEADER_SIZE + data_length + (1 if data_length else 0)
            if len(self.buffer) < frame_length:
                return None

            candidate = bytes(self.buffer[:frame_length])
            try:
                self._validate_frame(candidate)
            except LD6002CProtocolError:
                del self.buffer[0]
                continue

            del self.buffer[:frame_length]
            return candidate

        return None

    @staticmethod
    def _validate_frame(frame: bytes) -> tuple[int, int, bytes]:
        if len(frame) < HEADER_SIZE:
            raise LD6002CProtocolError("frame is shorter than the TinyFrame header")
        if frame[0] != SOF:
            raise LD6002CProtocolError("invalid SOF")

        data_length = int.from_bytes(frame[3:5], byteorder="big")
        if data_length > MAX_DATA_LENGTH:
            raise LD6002CProtocolError("data length exceeds the protocol limit")

        expected_length = HEADER_SIZE + data_length + (1 if data_length else 0)
        if len(frame) != expected_length:
            raise LD6002CProtocolError(
                f"frame length is {len(frame)}, expected {expected_length}"
            )

        if frame[7] != _checksum(frame[:7]):
            raise LD6002CProtocolError("invalid header checksum")

        data = frame[8 : 8 + data_length]
        if data_length and frame[-1] != _checksum(data):
            raise LD6002CProtocolError("invalid data checksum")

        message_type = int.from_bytes(frame[5:7], byteorder="big")
        return data_length, message_type, data


def _checksum(data: bytes) -> int:
    """Return the protocol checksum: bitwise NOT of the XOR of all bytes."""

    return (~reduce(xor, data, 0)) & 0xFF


def build_tinyframe(message_type: int, data: bytes, *, frame_id: int = 0) -> bytes:
    """Encode one documented TinyFrame command for the radar."""

    if not 0 <= frame_id <= 0xFFFF:
        raise ValueError("frame_id must fit in uint16")
    if not 0 <= message_type <= 0xFFFF:
        raise ValueError("message_type must fit in uint16")
    if len(data) > MAX_DATA_LENGTH:
        raise ValueError("data length exceeds the protocol limit")

    header = (
        bytes([SOF])
        + frame_id.to_bytes(2, byteorder="big")
        + len(data).to_bytes(2, byteorder="big")
        + message_type.to_bytes(2, byteorder="big")
    )
    frame = header + bytes([_checksum(header)]) + data
    return frame + (bytes([_checksum(data)]) if data else b"")


def build_user_log_command(enabled: bool, *, frame_id: int = 0) -> bytes:
    """Build official 0x010E command controlling active User log reports."""

    value = int(enabled).to_bytes(4, byteorder="little")
    return build_tinyframe(USER_LOG_TYPE, value, frame_id=frame_id)
