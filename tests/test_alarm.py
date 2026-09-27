from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

import pytest

from ld6002c_fall.alarm import DesktopAudioAlarm
from ld6002c_fall.radar_model import RadarFrame


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.finished = threading.Event()

    def poll(self) -> int | None:
        return 0 if self.finished.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self.finished.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self.finished.wait(timeout):
            raise subprocess.TimeoutExpired("ffplay", timeout)
        return 0

    def kill(self) -> None:
        self.finished.set()

    def finish(self) -> None:
        self.finished.set()


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


def test_desktop_alarm_runs_callback_after_playback_without_blocking(
    tmp_path: Path,
) -> None:
    sound = tmp_path / "alarm.mp3"
    sound.write_bytes(b"test audio")
    process = FakeProcess()
    callback_finished = threading.Event()
    alarm = DesktopAudioAlarm(
        sound,
        player="/usr/bin/ffplay",
        process_factory=lambda *_args, **_kwargs: process,  # type: ignore[arg-type]
    )
    alarm.emit(radar_frame(), "确认跌倒")

    started = time.perf_counter()
    registered = alarm.run_after_playback(callback_finished.set)
    elapsed = time.perf_counter() - started

    assert registered is True
    assert elapsed < 0.1
    assert callback_finished.is_set() is False
    process.finish()
    assert callback_finished.wait(1.0) is True


@pytest.mark.parametrize("volume", [-1, 101])
def test_desktop_alarm_rejects_invalid_volume(volume: int) -> None:
    with pytest.raises(ValueError, match="volume"):
        DesktopAudioAlarm("alarm.mp3", volume=volume)
