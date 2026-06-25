"""Mock radar reader for development without physical hardware."""

from __future__ import annotations

from datetime import datetime, timedelta

from .radar_model import RadarFrame


class MockRadarReader:
    """Generate deterministic LD6002C-like normalized frames.

    The mock timeline uses one frame per simulated second:
    - 0 to 10 seconds: human present, no fall.
    - 10 to 16 seconds: fall detected.
    - after 16 seconds: human present, no fall.
    """

    def __init__(
        self,
        start_time: datetime | None = None,
        interval_seconds: float = 1.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")

        self.start_time = start_time or datetime.now()
        self.interval_seconds = interval_seconds
        self._frame_index = 0

    def read(self) -> RadarFrame:
        """Return the next simulated radar frame."""

        elapsed_seconds = self._frame_index * self.interval_seconds
        timestamp = self.start_time + timedelta(seconds=elapsed_seconds)

        fall_detected = 10 <= elapsed_seconds < 16
        motion_state = "still" if fall_detected else "moving"

        frame = RadarFrame(
            timestamp=timestamp,
            human_present=True,
            fall_detected=fall_detected,
            motion_state=motion_state,
            raw=f"mock:index={self._frame_index};elapsed={elapsed_seconds:.1f}",
        )
        self._frame_index += 1
        return frame
