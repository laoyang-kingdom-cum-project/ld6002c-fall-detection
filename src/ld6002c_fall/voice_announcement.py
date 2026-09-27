"""Optional non-blocking speech, separate from emergency fall alarms."""

from __future__ import annotations

import base64
from collections.abc import Callable
import shutil
import subprocess
import sys
from typing import Protocol


class VoiceAnnouncementOutput(Protocol):
    """Output boundary for speech that supplements, but never replaces, alarms."""

    @property
    def ready(self) -> bool: ...

    @property
    def backend(self) -> str: ...

    def announce(self, text: str, *, delay_ms: int = 0) -> bool: ...

    def close(self) -> None: ...


class ConsoleVoiceAnnouncement:
    """Safe fallback that labels announcements without claiming audio playback."""

    def __init__(
        self,
        *,
        diagnostic_message: str = "当前平台未启用 Windows 中文语音。",
        powershell_found: bool = False,
        system_speech_loaded: bool | None = False,
        chinese_voice_found: bool | None = False,
    ) -> None:
        self.diagnostic_message = diagnostic_message
        self.powershell_found = powershell_found
        self.system_speech_loaded = system_speech_loaded
        self.chinese_voice_found = chinese_voice_found

    @property
    def ready(self) -> bool:
        return False

    @property
    def backend(self) -> str:
        return "console"

    def announce(self, text: str, *, delay_ms: int = 0) -> bool:
        del delay_ms
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
        self.powershell_found = self.powershell is not None
        self.system_speech_loaded: bool | None = None
        self.chinese_voice_found: bool | None = None
        if self.powershell is None:
            self._ready = False
            self.diagnostic_message = "未找到 powershell.exe 或 powershell。"
        elif not verify:
            self._ready = True
            self.diagnostic_message = "已跳过 Windows 中文语音能力探测。"
        else:
            self._ready = self._probe_capability()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def backend(self) -> str:
        return "windows-system-speech"

    def announce(self, text: str, *, delay_ms: int = 0) -> bool:
        if delay_ms < 0:
            raise ValueError("delay_ms must be greater than or equal to 0")
        if not self.ready or self.powershell is None:
            print(f"[Voice] {text}")
            return False
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        delay_script = (
            f"Start-Sleep -Milliseconds {delay_ms};" if delay_ms > 0 else ""
        )
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
            f"{delay_script}"
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
            self.powershell_found = False
            self.system_speech_loaded = False
            self.chinese_voice_found = False
            self.diagnostic_message = "未找到 powershell.exe 或 powershell。"
            return False
        script = (
            "$ErrorActionPreference='Stop';"
            "try{Add-Type -AssemblyName System.Speech}catch{exit 3};"
            "try{$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer}"
            "catch{exit 4};"
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
        except OSError as exc:
            self.powershell_found = False
            self.system_speech_loaded = None
            self.chinese_voice_found = None
            self.diagnostic_message = f"PowerShell 无法执行：{exc}"
            return False
        except subprocess.TimeoutExpired:
            self.system_speech_loaded = None
            self.chinese_voice_found = None
            self.diagnostic_message = "Windows 中文语音能力探测超时。"
            return False
        if result.returncode == 0:
            self.system_speech_loaded = True
            self.chinese_voice_found = True
            self.diagnostic_message = "System.Speech 已加载，并检测到 zh-* 中文语音。"
            return True
        if result.returncode == 2:
            self.system_speech_loaded = True
            self.chinese_voice_found = False
            self.diagnostic_message = "System.Speech 已加载，但未检测到 zh-* 中文语音。"
            return False
        if result.returncode == 3:
            self.system_speech_loaded = False
            self.chinese_voice_found = False
            self.diagnostic_message = "无法加载 Windows System.Speech。"
            return False
        if result.returncode == 4:
            self.system_speech_loaded = True
            self.chinese_voice_found = None
            self.diagnostic_message = "System.Speech 已加载，但无法创建语音合成器。"
            return False
        self.system_speech_loaded = None
        self.chinese_voice_found = None
        self.diagnostic_message = (
            f"Windows 中文语音能力探测失败，退出码 {result.returncode}。"
        )
        return False

    def close(self) -> None:
        """Each detached PowerShell process owns its short playback lifetime."""


def build_voice_announcement() -> VoiceAnnouncementOutput:
    """Return the offline Windows backend or an explicit console fallback."""

    if sys.platform == "win32":
        output = WindowsSpeechAnnouncement()
        if output.ready:
            return output
        return ConsoleVoiceAnnouncement(
            diagnostic_message=output.diagnostic_message,
            powershell_found=output.powershell_found,
            system_speech_loaded=output.system_speech_loaded,
            chinese_voice_found=output.chinese_voice_found,
        )
    return ConsoleVoiceAnnouncement(
        diagnostic_message="当前系统不是 Windows，未启用 System.Speech 中文语音。"
    )


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
