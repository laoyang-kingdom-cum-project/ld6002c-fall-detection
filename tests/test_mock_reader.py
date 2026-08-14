from __future__ import annotations

from datetime import datetime

from ld6002c_fall.mock_reader import MockRadarReader
from ld6002c_fall.radar_model import RadarFrame


def test_mock_reader_returns_radar_frame() -> None:
    reader = MockRadarReader(start_time=datetime(2026, 1, 1, 12, 0, 0))

    frame = reader.read()

    assert isinstance(frame, RadarFrame)
    assert frame.human_present is False
    assert frame.fall_detected is False


def test_fall_demo_mock_reader_contains_fall_period() -> None:
    reader = MockRadarReader(
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        scenario="fall-demo",
    )

    frames = [reader.read() for _ in range(20)]

    assert any(frame.fall_detected for frame in frames)


def test_presence_demo_contains_empty_and_present_periods() -> None:
    reader = MockRadarReader(
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        scenario="presence-demo",
    )

    frames = [reader.read() for _ in range(24)]

    assert any(frame.human_present for frame in frames)
    assert any(not frame.human_present for frame in frames)
