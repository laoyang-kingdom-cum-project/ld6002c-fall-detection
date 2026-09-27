from __future__ import annotations

import base64
from types import SimpleNamespace

import ld6002c_fall.voice_announcement as voice_module
from ld6002c_fall.voice_announcement import (
    ConsoleVoiceAnnouncement,
    WindowsSpeechAnnouncement,
    build_voice_announcement,
)


def test_console_voice_labels_fallback_without_claiming_audio(capsys) -> None:
    output = ConsoleVoiceAnnouncement()

    success = output.announce("检测到弯腰姿态，请注意安全。")

    assert success is False
    assert output.ready is False
    assert output.backend == "console"
    assert "[Voice] 检测到弯腰姿态" in capsys.readouterr().out


def test_windows_voice_uses_non_blocking_encoded_powershell_command() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def process_factory(command: list[str], **kwargs: object):
        calls.append((command, kwargs))
        return object()

    output = WindowsSpeechAnnouncement(
        powershell="powershell.exe",
        process_factory=process_factory,
        verify=False,
    )

    assert output.announce("当前监护状态已恢复正常。") is True
    command, kwargs = calls[0]
    assert command[:4] == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
    ]
    assert command[-2] == "-EncodedCommand"
    script = base64.b64decode(command[-1]).decode("utf-16le")
    assert "System.Speech.Synthesis.SpeechSynthesizer" in script
    assert "FromBase64String" in script
    assert "GetInstalledVoices" in script
    assert "当前监护状态" not in command[-1]
    assert kwargs["stdout"] is not None


def test_windows_voice_probe_requires_system_speech_and_chinese_voice() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object):
        calls.append(command)
        return SimpleNamespace(returncode=2)

    output = WindowsSpeechAnnouncement(
        powershell="powershell.exe",
        runner=runner,
    )

    assert output.ready is False
    assert len(calls) == 1
    script = base64.b64decode(calls[0][-1]).decode("utf-16le")
    assert "System.Speech" in script
    assert "Culture.Name -like 'zh-*'" in script


def test_voice_factory_falls_back_when_windows_probe_fails(monkeypatch) -> None:
    monkeypatch.setattr(voice_module.sys, "platform", "win32")
    monkeypatch.setattr(
        voice_module.shutil,
        "which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr(
        voice_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2),
    )

    output = build_voice_announcement()

    assert isinstance(output, ConsoleVoiceAnnouncement)
