from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import tomllib

from ld6002c_fall.community import (
    CommunityController,
    CommunityRuntimeHealth,
    CommunityTelemetryStore,
)
from ld6002c_fall.community_demo import (
    _build_environment,
    _port_available,
    build_parser,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


def test_community_demo_defaults_to_ai_host_all_interfaces_and_port_8501() -> None:
    args = build_parser().parse_args([])

    assert args.enable_ai is True
    assert args.host == "0.0.0.0"
    assert args.port == 8501
    assert args.ollama_base_url == "http://127.0.0.1:11434"
    assert args.ollama_model == "qwen3:0.6b"


def test_community_demo_exports_dashboard_process_configuration(tmp_path) -> None:
    args = build_parser().parse_args(
        [
            "--state-path", str(tmp_path / "state.json"),
            "--event-path", str(tmp_path / "events.csv"),
            "--telemetry-dir", str(tmp_path / "telemetry"),
            "--no-enable-ai",
            "--no-audio-alarm",
        ]
    )

    env = _build_environment(args)

    assert env["AI_ENABLED"] == "false"
    assert env["AUDIO_ALARM_ENABLED"] == "false"
    assert env["LD6002C_COMMUNITY_STATE_PATH"] == str(
        (tmp_path / "state.json").resolve()
    )
    assert env["LD6002C_COMMUNITY_TELEMETRY_DIR"] == str(
        (tmp_path / "telemetry").resolve()
    )


def test_port_probe_reuses_recently_closed_listener_address() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    assert _port_available("127.0.0.1", port) is True


def test_reset_clears_demo_state_events_and_telemetry_without_starting_server(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "state.json"
    event_path = tmp_path / "events.csv"
    telemetry_dir = tmp_path / "telemetry"
    controller = CommunityController.from_paths(
        ROOT / "config" / "community.json",
        state_path,
        event_path,
    )
    controller.inject_demo("B1-101", "FALL")
    telemetry = CommunityTelemetryStore(telemetry_dir)
    (telemetry_dir / "B1-101.csv").write_text("demo", encoding="utf-8")
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ld6002c-community-demo",
            "--reset",
            "--config-path", str(ROOT / "config" / "community.json"),
            "--state-path", str(state_path),
            "--event-path", str(event_path),
            "--telemetry-dir", str(telemetry_dir),
        ],
    )

    main()

    reset = CommunityController.from_paths(
        ROOT / "config" / "community.json",
        state_path,
        event_path,
    )
    assert {state.status for state in reset.states().values()} == {"NORMAL"}
    assert not list(telemetry_dir.glob("*.csv"))
    assert reset.recent_events(20) == []


def test_pyproject_exposes_community_demo_console_command() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["scripts"]["ld6002c-community-demo"] == (
        "ld6002c_fall.community_demo:main"
    )


def test_launcher_starts_runtime_before_streamlit_and_stops_it(
    tmp_path,
    monkeypatch,
) -> None:
    actions: list[str] = []

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs) -> None:
            actions.append("runtime-created")

        def start(self) -> None:
            actions.append("runtime-started")

        def stop(self) -> None:
            actions.append("runtime-stopped")

    class FakeProcess:
        returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            actions.append("streamlit-waited")
            self.returncode = 0
            return 0

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            actions.append("streamlit-terminated")
            self.returncode = 0

        def kill(self) -> None:
            actions.append("streamlit-killed")
            self.returncode = -9

    def fake_popen(*_args, **_kwargs) -> FakeProcess:
        actions.append("streamlit-started")
        return FakeProcess()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ld6002c-community-demo",
            "--host", "127.0.0.1",
            "--port", "18501",
            "--no-enable-ai",
            "--no-audio-alarm",
            "--no-open-browser",
            "--config-path", str(ROOT / "config" / "community.json"),
            "--state-path", str(tmp_path / "state.json"),
            "--event-path", str(tmp_path / "events.csv"),
            "--telemetry-dir", str(tmp_path / "telemetry"),
            "--runtime-path", str(tmp_path / "runtime.json"),
        ],
    )
    monkeypatch.setattr("ld6002c_fall.community_demo.CommunityDemoRuntime", FakeRuntime)
    monkeypatch.setattr("ld6002c_fall.community_demo._port_available", lambda *_: True)
    monkeypatch.setattr("ld6002c_fall.community_demo._wait_for_dashboard", lambda *_: True)
    monkeypatch.setattr(
        "ld6002c_fall.community_demo._ready_runtime_health",
        lambda *_args, **_kwargs: (
            actions.append("runtime-ready")
            or CommunityRuntimeHealth(
                runtime="RUNNING",
                telemetry="ACTIVE",
                ollama="DISABLED",
            )
        ),
    )
    monkeypatch.setattr("ld6002c_fall.community_demo.subprocess.Popen", fake_popen)

    main()

    assert actions == [
        "runtime-created",
        "runtime-started",
        "runtime-ready",
        "streamlit-started",
        "streamlit-waited",
        "runtime-stopped",
    ]
