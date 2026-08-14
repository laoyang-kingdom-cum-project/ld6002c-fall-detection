"""Business state transitions between FallDetector and output devices."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime

from .device_protocol import DeviceState
from .event_logger import SystemEvent
from .fall_detector import DetectionResult, SystemState
from .radar_model import RadarFrame


STATE_MAP: dict[SystemState, DeviceState] = {
    "无人": "NORMAL",
    "正常有人": "NORMAL",
    "观察中": "OBSERVING",
    "疑似跌倒": "SUSPECTED_FALL",
    "确认跌倒": "CONFIRMED_FALL",
}


@dataclass(frozen=True)
class ControllerResult:
    """Device-facing result derived from one detector update."""

    state: DeviceState
    should_alarm: bool
    events: tuple[SystemEvent, ...]


class SystemController:
    """Track device-facing state and cancellation for the current fall."""

    def __init__(self) -> None:
        self._state: DeviceState = "DISCONNECTED"
        self._cancelled_for_current_fall = False
        self._lock = threading.Lock()

    @property
    def state(self) -> DeviceState:
        with self._lock:
            return self._state

    def process(
        self,
        frame: RadarFrame,
        detection: DetectionResult,
        source: str,
    ) -> ControllerResult:
        """Apply one detector result and emit events for meaningful transitions."""

        with self._lock:
            previous_state = self._state
            if not frame.fall_detected:
                self._cancelled_for_current_fall = False

            mapped_state = STATE_MAP[detection.state]
            if frame.fall_detected and self._cancelled_for_current_fall:
                next_state: DeviceState = "CANCELLED"
                should_alarm = False
            else:
                next_state = mapped_state
                should_alarm = detection.should_alarm

            events: list[SystemEvent] = []
            if next_state == "SUSPECTED_FALL" and previous_state != next_state:
                events.append(
                    SystemEvent(frame.timestamp, "FALL_SUSPECTED", next_state, source)
                )
            if next_state == "CONFIRMED_FALL" and previous_state != next_state:
                events.append(
                    SystemEvent(frame.timestamp, "FALL_CONFIRMED", next_state, source)
                )
            if should_alarm:
                events.append(
                    SystemEvent(frame.timestamp, "ALARM_STARTED", next_state, source)
                )

            self._state = next_state
            return ControllerResult(next_state, should_alarm, tuple(events))

    def cancel_alarm(self, timestamp: datetime, source: str) -> SystemEvent | None:
        """Cancel an active confirmed alarm until the fall signal clears."""

        with self._lock:
            if self._state != "CONFIRMED_FALL":
                return None
            self._cancelled_for_current_fall = True
            self._state = "CANCELLED"
            return SystemEvent(
                timestamp=timestamp,
                event="ALARM_CANCELLED",
                state="CANCELLED",
                source=source,
                details="Alarm cancelled from connected device",
            )
