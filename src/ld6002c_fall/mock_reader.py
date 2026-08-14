"""Mock radar reader for development without physical hardware."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from .radar_model import RadarFrame

MockScenario = Literal["empty", "normal", "fall-demo", "presence-demo"]
MOCK_SCENARIOS: tuple[MockScenario, ...] = (
    "empty",
    "normal",
    "fall-demo",
    "presence-demo",
)


class MockRadarReader:
    """Generate deterministic LD6002C-like normalized frames.

    Scenarios use one frame per simulated second:
    - empty: no human present, no fall alarm.
    - normal: human present, no fall alarm.
    - fall-demo:
    - 0 to 10 seconds: human present, no fall.
    - 10 to 16 seconds: fall detected.
    - after 16 seconds: human present, no fall.
    - presence-demo: cycles between empty room and normal human presence.
    """

    def __init__(
        self,
        start_time: datetime | None = None,
        interval_seconds: float = 1.0,
        scenario: MockScenario = "empty",
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        if scenario not in MOCK_SCENARIOS:
            choices = ", ".join(MOCK_SCENARIOS)
            raise ValueError(f"scenario must be one of: {choices}")

        self.start_time = start_time or datetime.now()
        self.interval_seconds = interval_seconds
        self.scenario = scenario
        self._frame_index = 0

    def read(self) -> RadarFrame:
        """Return the next simulated radar frame."""

        elapsed_seconds = self._frame_index * self.interval_seconds
        timestamp = self.start_time + timedelta(seconds=elapsed_seconds)
        human_present, fall_detected, motion_state = self._state_for_elapsed(
            elapsed_seconds
        )

        frame = RadarFrame(
            timestamp=timestamp,
            human_present=human_present,
            fall_detected=fall_detected,
            motion_state=motion_state,
            raw=(
                f"mock:scenario={self.scenario};index={self._frame_index};"
                f"elapsed={elapsed_seconds:.1f}"
            ),
        )
        self._frame_index += 1
        return frame

    def _state_for_elapsed(self, elapsed_seconds: float) -> tuple[bool, bool, str]:
        if self.scenario == "empty":
            return False, False, "none"

        if self.scenario == "normal":
            return True, False, "moving"

        if self.scenario == "fall-demo":
            fall_detected = 10 <= elapsed_seconds < 16
            return True, fall_detected, "still" if fall_detected else "moving"

        if self.scenario == "presence-demo":
            cycle_second = int(elapsed_seconds) % 24
            human_present = 6 <= cycle_second < 18
            return human_present, False, "moving" if human_present else "none"

        raise RuntimeError(f"unsupported mock scenario: {self.scenario}")
