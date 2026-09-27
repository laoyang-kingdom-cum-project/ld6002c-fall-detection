"""Optional non-blocking status announcements, separate from fall alarms."""

from __future__ import annotations

import base64
from collections.abc import Callable
import shutil
import subprocess
import sys
from typing import Protocol


class VoiceAnnouncementOutput(Protocol):
    """Output boundary for optional non-emergency status speech."""

    @property
    def ready(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def announce(self, text: str) -> bool: ...

    def close(self) -> None: ...


class ConsoleVoiceAnnouncement:
    """Safe fallback that labels announcements without claiming audio playback."""

    @property
    def ready(self) -> bool:
        return False

    @property
    def backend(self) -> str:
        return "console"

    def announce(self, text: str) -> bool:
        print(f"[Voice] {text}")
        return False

    def close(self) -> None:
        """Console output owns no resource."""


class WindowsSpeechAnnouncement:
    """Launch Windows System.Speech asynchronously through PowerShell."""

    def __init__(
        self,
        *,
        powershell: str | None = None,
        process_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
        verify: bool = True,
    ) -> None:
        self.powershell = powershell or shutil.which("powershell.exe") or shutil.which(
            "powershell"
        )
        self._process_factory = process_factory
        self._runner = runner or subprocess.run
        self._ready = self.powershell is not None and (
            not verify or self._probe_capability()
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def backend(self) -> str:
        return "windows-system-speech"

    def announce(self, text: str) -> bool:
        if not self.ready or self.powershell is None:
            print(f"[Voice] {text}")
            return False
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Speech;"
            "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$voice=$speaker.GetInstalledVoices()|Where-Object{"
            "$_.Enabled -and $_.VoiceInfo.Culture.Name -like 'zh-*'}|"
            "Select-Object -First 1;"
            "if($null -eq $voice){throw 'Chinese speech voice is unavailable'};"
            "$speaker.SelectVoice($voice.VoiceInfo.Name);"
            "$text=[System.Text.Encoding]::UTF8.GetString("
            f"[System.Convert]::FromBase64String('{encoded_text}'));"
            "$speaker.Speak($text);$speaker.Dispose();"
        )
        command = _powershell_command(self.powershell, script)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            print(f"[Voice] Windows 语音启动失败：{exc}")
            print(f"[Voice] {text}")
            return False
        return True

    def _probe_capability(self) -> bool:
        if self.powershell is None:
            return False
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Speech;"
            "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$voices=@($speaker.GetInstalledVoices()|Where-Object{"
            "$_.Enabled -and $_.VoiceInfo.Culture.Name -like 'zh-*'});"
            "$speaker.Dispose();"
            "if($voices.Count -lt 1){exit 2};exit 0;"
        )
        try:
            result = self._runner(
                _powershell_command(self.powershell, script),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def close(self) -> None:
        """Each detached PowerShell process owns its short playback lifetime."""


def build_voice_announcement() -> VoiceAnnouncementOutput:
    """Return the offline Windows backend or an explicit console fallback."""

    if sys.platform == "win32":
        output = WindowsSpeechAnnouncement()
        if output.ready:
            return output
    return ConsoleVoiceAnnouncement()


def _powershell_command(powershell: str, script: str) -> list[str]:
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded_script,
    ]
