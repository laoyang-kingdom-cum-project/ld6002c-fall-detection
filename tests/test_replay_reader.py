from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ld6002c_fall.ld6002c_parser import LD6002CParser
from ld6002c_fall.replay_reader import ReplayRadarReader


NOW = datetime(2026, 8, 14, 12, 0, 0)


def test_replay_reader_parses_binary_capture_in_small_chunks(tmp_path: Path) -> None:
    capture = tmp_path / "status.bin"
    capture.write_bytes(
        bytes.fromhex("01 00 00 00 01 0e 02 f3 01 fe")
        + bytes.fromhex("01 00 01 00 01 0f 09 f8 01 fe")
    )
    parser = LD6002CParser(clock=lambda: NOW)

    with ReplayRadarReader(capture, parser=parser, chunk_size=3) as reader:
        frame = reader.read()
        assert frame is not None
        assert frame.timestamp == NOW
        assert frame.human_present is True
        assert frame.fall_detected is True

        assert reader.read() is None
        assert reader.finished is True


def test_replay_reader_accepts_arbitrary_incomplete_bytes(tmp_path: Path) -> None:
    capture = tmp_path / "unknown.bin"
    capture.write_bytes(b"not-a-complete-frame\x01\x00")

    with ReplayRadarReader(capture, chunk_size=2) as reader:
        assert reader.read() is None
        assert reader.finished is True
