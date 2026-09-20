from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "deploy" / "windows"


def test_windows_entrypoints_and_runtime_scripts_exist() -> None:
    expected = (
        ROOT / "START_WINDOWS.bat",
        ROOT / "STOP_WINDOWS.bat",
        ROOT / "WINDOWS_CHECK.bat",
        WINDOWS_DIR / "start.ps1",
        WINDOWS_DIR / "stop.ps1",
        WINDOWS_DIR / "doctor.ps1",
        WINDOWS_DIR / "run-service.ps1",
        WINDOWS_DIR / "common.ps1",
        WINDOWS_DIR / "config.example.cmd",
        WINDOWS_DIR / "README.md",
    )

    assert all(path.is_file() for path in expected)


def test_startup_scripts_do_not_attempt_online_installation() -> None:
    scripts = (
        ROOT / "START_WINDOWS.bat",
        ROOT / "STOP_WINDOWS.bat",
        ROOT / "WINDOWS_CHECK.bat",
        *WINDOWS_DIR.glob("*.ps1"),
    )
    forbidden = (
        "pip install",
        "ollama pull",
        "winget ",
        "choco ",
        "curl http",
        "git pull",
    )
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in scripts)

    assert all(command not in combined for command in forbidden)


def test_service_runner_uses_the_existing_cli_and_mock_fallback() -> None:
    script = (WINDOWS_DIR / "run-service.ps1").read_text(encoding="utf-8")

    assert '"-m", "ld6002c_fall.main"' in script
    assert '"--mode", $Mode' in script
    assert '"--enable-ai"' in script
    assert '"--port", $RadarPort, "--baudrate"' in script
    assert '"--mock-scenario", "fall-demo"' in script
    assert '"--suspect-seconds", "1"' in script
    assert '"--confirm-seconds", "2"' in script
    assert '"--disable-audio-alarm"' in script
    assert "-m streamlit run" in script


def test_stop_script_targets_recorded_process_trees_instead_of_python_name() -> None:
    script = (WINDOWS_DIR / "stop.ps1").read_text(encoding="utf-8").casefold()

    assert "radar.pid" in script
    assert "dashboard.pid" in script
    assert "taskkill.exe /pid" in script
    assert "taskkill /im python" not in script
