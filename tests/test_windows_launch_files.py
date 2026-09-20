from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "deploy" / "windows"


def test_windows_entrypoints_and_runtime_scripts_exist() -> None:
    expected = (
        ROOT / "INSTALL_WINDOWS_OFFLINE.bat",
        ROOT / "START_WINDOWS.bat",
        ROOT / "STOP_WINDOWS.bat",
        ROOT / "WINDOWS_CHECK.bat",
        WINDOWS_DIR / "start.ps1",
        WINDOWS_DIR / "stop.ps1",
        WINDOWS_DIR / "doctor.ps1",
        WINDOWS_DIR / "install-offline.ps1",
        WINDOWS_DIR / "run-service.ps1",
        WINDOWS_DIR / "common.ps1",
        WINDOWS_DIR / "config.example.cmd",
        WINDOWS_DIR / "README.md",
    )

    assert all(path.is_file() for path in expected)


def test_startup_scripts_do_not_attempt_online_installation() -> None:
    scripts = (
        ROOT / "INSTALL_WINDOWS_OFFLINE.bat",
        ROOT / "START_WINDOWS.bat",
        ROOT / "STOP_WINDOWS.bat",
        ROOT / "WINDOWS_CHECK.bat",
        *WINDOWS_DIR.glob("*.ps1"),
    )
    forbidden = (
        "ollama pull",
        "winget ",
        "choco ",
        "curl http",
        "git pull",
    )
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in scripts)

    assert all(command not in combined for command in forbidden)

    runtime_scripts = tuple(path for path in scripts if path.name != "install-offline.ps1")
    runtime_combined = "\n".join(
        path.read_text(encoding="utf-8").casefold() for path in runtime_scripts
    )
    assert "pip install" not in runtime_combined


def test_offline_installer_uses_only_packaged_python_and_model_assets() -> None:
    script = (WINDOWS_DIR / "install-offline.ps1").read_text(encoding="utf-8")
    folded = script.casefold()

    assert 'get-command "py.exe"' in folded
    assert 'prefixarguments @("-3.14")' in folded
    assert "$probe.info.bits -eq 64" in folded
    assert "--no-index" in script
    assert "--disable-pip-version-check" in script
    assert "--only-binary=:all:" in script
    assert "--find-links" in script
    assert '"project-wheel"' in script
    assert '"ld6002c_fall_detection-*.whl"' in script
    assert "Get-OllamaModelFileStatus" in script
    assert "Merge-ModelStore" in script
    assert "robocopy.exe" in script
    assert " /E " in script
    assert "/MIR" not in script
    assert "ollama pull" not in folded


def test_doctor_treats_an_installed_but_stopped_ollama_as_a_warning() -> None:
    script = (WINDOWS_DIR / "doctor.ps1").read_text(encoding="utf-8")

    assert "Ollama service is currently stopped" in script
    assert "START_WINDOWS.bat will start it automatically" in script
    assert "Offline model store" in script
    assert 'Report-Error ("Ollama API offline' not in script


def test_windows_start_requires_the_installed_python_314_x64_environment() -> None:
    script = (WINDOWS_DIR / "start.ps1").read_text(encoding="utf-8")

    assert "sys.version_info[:2] == (3, 14)" in script
    assert "struct.calcsize('P') * 8 == 64" in script
    assert "Run INSTALL_WINDOWS_OFFLINE.bat" in script


def test_large_offline_payloads_are_not_tracked_by_default() -> None:
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "models/" in ignore_rules


def test_requirements_reference_has_no_builder_absolute_path() -> None:
    requirements = ROOT / "requirements-win.txt"
    if requirements.exists():
        content = requirements.read_text(encoding="utf-8").casefold()
        assert "ld6002c-fall-detection @ file:" not in content


def test_windows_wheelhouse_targets_cpython_314_not_311() -> None:
    names = [path.name.casefold() for path in (ROOT / "wheelhouse").glob("*.whl")]

    assert names
    assert not any("cp311" in name for name in names)
    for package in (
        "charset_normalizer",
        "httptools",
        "markupsafe",
        "numpy",
        "pandas",
        "pillow",
        "pyarrow",
        "rpds_py",
        "websockets",
    ):
        assert any(name.startswith(f"{package}-") and "cp314" in name for name in names)


def test_project_wheel_matches_current_windows_runtime_contract() -> None:
    wheels = sorted((ROOT / "project-wheel").glob("ld6002c_fall_detection-*.whl"))

    assert wheels
    with ZipFile(wheels[-1]) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
        names = set(archive.namelist())

    assert "Requires-Python: >=3.11" in metadata
    assert "Requires-Dist: streamlit<2,>=1.59" in metadata
    assert "ld6002c_fall/community/controller.py" in names
    assert "ld6002c_fall/community/state_store.py" in names


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
