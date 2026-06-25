from __future__ import annotations

from datetime import datetime

from ld6002c_fall.mock_reader import MockRadarReader
from ld6002c_fall.radar_model import RadarFrame


def test_mock_reader_returns_radar_frame() -> None:
    reader = MockRadarReader(start_time=datetime(2026, 1, 1, 12, 0, 0))

    frame = reader.read()

    assert isinstance(frame, RadarFrame)
    assert frame.human_present is True
    assert frame.fall_detected is False


def test_mock_reader_contains_fall_period() -> None:
    reader = MockRadarReader(start_time=datetime(2026, 1, 1, 12, 0, 0))

    frames = [reader.read() for _ in range(20)]

    assert any(frame.fall_detected for frame in frames)
