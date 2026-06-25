"""Simple alarm implementations."""

from __future__ import annotations

from .radar_model import RadarFrame


class ConsoleAlarm:
    """Print a fall alarm to the console."""

    def emit(self, frame: RadarFrame, state: str) -> None:
        timestamp = frame.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 40)
        print("⚠️ 跌倒报警")
        print(f"时间：{timestamp}")
        print(f"状态：{state}")
        print("=" * 40)
