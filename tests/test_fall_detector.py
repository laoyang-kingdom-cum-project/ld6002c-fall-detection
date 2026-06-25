from __future__ import annotations

from datetime import datetime, timedelta

from ld6002c_fall.fall_detector import FallDetector
from ld6002c_fall.radar_model import RadarFrame


def make_frame(base: datetime, offset_seconds: int, fall_detected: bool) -> RadarFrame:
    return RadarFrame(
        timestamp=base + timedelta(seconds=offset_seconds),
        human_present=True,
        fall_detected=fall_detected,
        motion_state="still" if fall_detected else "moving",
        raw=f"test:{offset_seconds}",
    )


def test_confirmed_fall_after_confirm_seconds() -> None:
    detector = FallDetector(suspect_seconds=2, confirm_seconds=5, alarm_cooldown=30)
    base = datetime(2026, 1, 1, 12, 0, 0)

    result = None
    for seconds in range(6):
        result = detector.update(make_frame(base, seconds, fall_detected=True))

    assert result is not None
    assert result.state == "确认跌倒"
    assert result.should_alarm is True


def test_short_fall_does_not_confirm() -> None:
    detector = FallDetector(suspect_seconds=2, confirm_seconds=5, alarm_cooldown=30)
    base = datetime(2026, 1, 1, 12, 0, 0)

    first = detector.update(make_frame(base, 0, fall_detected=True))
    second = detector.update(make_frame(base, 1, fall_detected=True))
    reset = detector.update(make_frame(base, 2, fall_detected=False))

    assert first.state == "观察中"
    assert second.state == "观察中"
    assert reset.state == "正常有人"
    assert first.should_alarm is False
    assert second.should_alarm is False
    assert reset.should_alarm is False
