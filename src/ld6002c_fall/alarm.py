"""Simple alarm implementations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Protocol, runtime_checkable

from .radar_model import RadarFrame


class AlarmOutput(Protocol):
    """Output boundary used by the detection pipeline."""

    def emit(self, frame: RadarFrame, state: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class PlaybackCompletionAlarm(Protocol):
    """Optional alarm capability for work that follows real audio playback."""

    def run_after_playback(self, callback: Callable[[], None]) -> bool:
        """Run callback after active playback ends; return whether it was registered."""


class ConsoleAlarm:
    """Print a fall alarm to the console."""

    def emit(self, frame: RadarFrame, state: str) -> None:
        timestamp = frame.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 40)
        print("⚠️ 跌倒报警")
        print(f"时间：{timestamp}")
        print(f"状态：{state}")
        print("=" * 40)

    def close(self) -> None:
        """Console output owns no resource."""


class DesktopAudioAlarm(ConsoleAlarm):
    """Print an alarm and play one local audio file without blocking detection."""

    def __init__(
        self,
        sound_path: str | Path,
        *,
        volume: int = 100,
        player: str | None = None,
        process_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        if not 0 <= volume <= 100:
            raise ValueError("volume must be between 0 and 100")
        self.sound_path = Path(sound_path).expanduser()
        self.volume = volume
        self.player = player if player is not None else shutil.which("ffplay")
        self._process_factory = process_factory
        self._process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        """Whether both the configured file and ffplay are available."""

        return self.sound_path.is_file() and self.player is not None

    def emit(self, frame: RadarFrame, state: str) -> None:
        super().emit(frame, state)
        if not self.sound_path.is_file():
            print(f"[Alarm] 音频文件不存在：{self.sound_path}")
            return
        if self.player is None:
            print("[Alarm] 未找到 ffplay，仅保留控制台报警")
            return
        command = [
            self.player,
            "-nodisp",
            "-autoexit",
            "-nostats",
            "-loglevel",
            "error",
            "-volume",
            str(self.volume),
            str(self.sound_path),
        ]
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                print("[Alarm] 电脑语音报警正在播放")
                return
            try:
                self._process = self._process_factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                print(f"[Alarm] 电脑语音播放失败：{exc}")
                return
        print(
            f"[Alarm] 电脑正在播放 {self.sound_path.name} "
            f"(音量 {self.volume}%)"
        )

    def run_after_playback(self, callback: Callable[[], None]) -> bool:
        """Wait for the active ffplay process on a daemon thread."""

        with self._process_lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            thread = threading.Thread(
                target=self._wait_then_run,
                args=(process, callback),
                name="desktop-audio-alarm-completion",
                daemon=True,
            )
            thread.start()
        return True

    def _wait_then_run(
        self,
        process: subprocess.Popen[bytes],
        callback: Callable[[], None],
    ) -> None:
        try:
            process.wait()
        except Exception as exc:
            print(f"[Alarm] 等待电脑语音报警结束失败：{exc}")
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None
        try:
            callback()
        except Exception as exc:
            print(f"[Alarm] 播放完成回调失败：{exc}")

    def close(self) -> None:
        with self._process_lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)
