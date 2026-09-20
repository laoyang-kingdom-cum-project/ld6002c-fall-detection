from __future__ import annotations

from datetime import datetime

from ld6002c_fall.mock_reader import MockRadarReader, build_mock_radar_frame
from ld6002c_fall.radar_model import RadarFrame


def test_mock_reader_returns_radar_frame() -> None:
    reader = MockRadarReader(start_time=datetime(2026, 1, 1, 12, 0, 0))

    frame = reader.read()

    assert isinstance(frame, RadarFrame)
    assert frame.human_present is False
    assert frame.fall_detected is False
    assert frame.points == ()


def test_fall_demo_mock_reader_contains_fall_period() -> None:
    reader = MockRadarReader(
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        scenario="fall-demo",
    )

    frames = [reader.read() for _ in range(20)]

    assert any(frame.fall_detected for frame in frames)
    fall_frame = next(frame for frame in frames if frame.fall_detected)
    assert len(fall_frame.points) == 7
    assert all(point.z < 0.5 for point in fall_frame.points)


def test_normal_mock_reader_generates_coordinate_points() -> None:
    reader = MockRadarReader(
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        scenario="normal",
    )

    frame = reader.read()

    assert len(frame.points) == 7
    assert {point.cluster_id for point in frame.points} == {1}
    assert max(point.z for point in frame.points) > 1.5


def test_presence_demo_contains_empty_and_present_periods() -> None:
    reader = MockRadarReader(
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        scenario="presence-demo",
    )

    frames = [reader.read() for _ in range(24)]

    assert any(frame.human_present for frame in frames)
    assert any(not frame.human_present for frame in frames)


def test_community_warning_cloud_has_mid_height_centroid() -> None:
    frame = build_mock_radar_frame("WARNING", 3.0)

    z_center = sum(point.z for point in frame.points) / len(frame.points)
    assert 0.7 <= z_center <= 1.0
    assert frame.motion_state == "unstable"
