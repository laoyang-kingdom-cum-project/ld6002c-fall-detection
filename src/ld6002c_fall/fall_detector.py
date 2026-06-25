"""Python secondary decision state machine for fall detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .radar_model import RadarFrame

SystemState = Literal["无人", "正常有人", "观察中", "疑似跌倒", "确认跌倒"]


@dataclass(frozen=True)
class DetectionResult:
    """Output of the fall detection state machine."""

    state: SystemState
    should_alarm: bool
    fall_duration_seconds: float


class FallDetector:
    """Track fall signal duration and apply alarm cooldown rules."""

    def __init__(
        self,
        suspect_seconds: float = 2.0,
        confirm_seconds: float = 5.0,
        alarm_cooldown: float = 30.0,
    ) -> None:
        if suspect_seconds < 0:
            raise ValueError("suspect_seconds must be non-negative")
        if confirm_seconds < suspect_seconds:
            raise ValueError("confirm_seconds must be greater than or equal to suspect_seconds")
        if alarm_cooldown < 0:
            raise ValueError("alarm_cooldown must be non-negative")

        self.suspect_seconds = suspect_seconds
        self.confirm_seconds = confirm_seconds
        self.alarm_cooldown = alarm_cooldown
        self._fall_started_at: datetime | None = None
        self._last_alarm_at: datetime | None = None

    def update(self, frame: RadarFrame) -> DetectionResult:
        """Update the state machine with one normalized radar frame."""

        if not frame.fall_detected:
            self._fall_started_at = None
            state: SystemState = "正常有人" if frame.human_present else "无人"
            return DetectionResult(state=state, should_alarm=False, fall_duration_seconds=0.0)

        if self._fall_started_at is None:
            self._fall_started_at = frame.timestamp

        fall_duration = max(
            0.0,
            (frame.timestamp - self._fall_started_at).total_seconds(),
        )

        if fall_duration >= self.confirm_seconds:
            should_alarm = self._should_alarm(frame.timestamp)
            if should_alarm:
                self._last_alarm_at = frame.timestamp
            return DetectionResult(
                state="确认跌倒",
                should_alarm=should_alarm,
                fall_duration_seconds=fall_duration,
            )

        if fall_duration >= self.suspect_seconds:
            return DetectionResult(
                state="疑似跌倒",
                should_alarm=False,
                fall_duration_seconds=fall_duration,
            )

        return DetectionResult(
            state="观察中",
            should_alarm=False,
            fall_duration_seconds=fall_duration,
        )

    def _should_alarm(self, timestamp: datetime) -> bool:
        if self._last_alarm_at is None:
            return True

        elapsed = (timestamp - self._last_alarm_at).total_seconds()
        return elapsed >= self.alarm_cooldown
