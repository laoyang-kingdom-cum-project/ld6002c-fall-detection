from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from ld6002c_fall.alarm import DesktopAudioAlarm
from ld6002c_fall.radar_model import RadarFrame


class FakeProcess:
    def __init__(self) -> None:
        self.running = True
        self.terminated = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def wait(self, timeout: float) -> int:
        del timeout
        self.running = False
        return 0

    def kill(self) -> None:
        self.running = False


def radar_frame() -> RadarFrame:
    return RadarFrame(
        timestamp=datetime(2026, 8, 18, 12, 0, 0),
        human_present=True,
        fall_detected=True,
        motion_state="still",
        raw="test",
    )


def test_desktop_alarm_starts_ffplay_without_blocking(tmp_path: Path) -> None:
    sound = tmp_path / "alarm.mp3"
    sound.write_bytes(b"test audio")
    calls: list[tuple[list[str], dict[str, Any]]] = []
    process = FakeProcess()

    def start(command: list[str], **kwargs: Any) -> FakeProcess:
        calls.append((command, kwargs))
        return process

    alarm = DesktopAudioAlarm(
        sound,
        volume=65,
        player="/usr/bin/ffplay",
        process_factory=start,  # type: ignore[arg-type]
    )

    alarm.emit(radar_frame(), "确认跌倒")

    command, options = calls[0]
    assert command[0] == "/usr/bin/ffplay"
    assert command[command.index("-volume") + 1] == "65"
    assert command[-1] == str(sound)
    assert options["stdin"] is not None
    alarm.close()
    assert process.terminated is True


def test_desktop_alarm_keeps_console_fallback_when_sound_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alarm = DesktopAudioAlarm(
        tmp_path / "missing.mp3",
        player="/usr/bin/ffplay",
    )

    alarm.emit(radar_frame(), "确认跌倒")

    output = capsys.readouterr().out
    assert "跌倒报警" in output
    assert "音频文件不存在" in output


@pytest.mark.parametrize("volume", [-1, 101])
def test_desktop_alarm_rejects_invalid_volume(volume: int) -> None:
    with pytest.raises(ValueError, match="volume"):
        DesktopAudioAlarm("alarm.mp3", volume=volume)
