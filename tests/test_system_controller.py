from __future__ import annotations

from datetime import datetime, timedelta

from ld6002c_fall.fall_detector import FallDetector
from ld6002c_fall.radar_model import RadarFrame
from ld6002c_fall.system_controller import SystemController


BASE = datetime(2026, 8, 14, 12, 0, 0)


def make_frame(seconds: int, fall: bool) -> RadarFrame:
    return RadarFrame(
        timestamp=BASE + timedelta(seconds=seconds),
        human_present=True,
        fall_detected=fall,
        motion_state="still" if fall else "moving",
        raw="test",
    )


def update(
    controller: SystemController,
    detector: FallDetector,
    seconds: int,
    fall: bool,
):
    frame = make_frame(seconds, fall)
    return controller.process(frame, detector.update(frame), source="test")


def test_cancelled_alarm_does_not_repeat_for_same_fall() -> None:
    detector = FallDetector(suspect_seconds=2, confirm_seconds=5, alarm_cooldown=1)
    controller = SystemController()

    for second in range(5):
        update(controller, detector, second, True)
    confirmed = update(controller, detector, 5, True)
    assert confirmed.state == "CONFIRMED_FALL"
    assert confirmed.should_alarm is True
    assert {event.raw for event in confirmed.events} == {"test"}
    assert {event.event for event in confirmed.events} == {
        "FALL_DETECTED",
        "ALARM_TRIGGERED",
    }

    cancellation = controller.cancel_alarm(BASE + timedelta(seconds=6), "sticks3:test")
    assert cancellation is not None
    assert cancellation.event == "ALARM_CANCELLED"
    assert cancellation.raw == "test"
    assert controller.state == "CANCELLED"

    still_falling = update(controller, detector, 10, True)
    assert still_falling.state == "CANCELLED"
    assert still_falling.should_alarm is False

    recovered = update(controller, detector, 11, False)
    assert recovered.state == "NORMAL"


def test_cancel_is_ignored_without_confirmed_alarm() -> None:
    controller = SystemController()

    assert controller.cancel_alarm(BASE, "sticks3:test") is None
    assert controller.state == "DISCONNECTED"
