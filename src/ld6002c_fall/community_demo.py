"""One-command launcher for the file-backed community classroom demo."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

from .ai import OllamaFallAI
from .alarm import ConsoleAlarm, DesktopAudioAlarm
from .community import (
    CommunityController,
    CommunityDemoRuntime,
    CommunityRuntimeHealthStore,
    CommunityTelemetryStore,
)
from .config import (
    DEFAULT_ALARM_SOUND_PATH,
    DEFAULT_ALARM_VOLUME,
    DEFAULT_COMMUNITY_CONFIG_PATH,
    DEFAULT_COMMUNITY_EVENT_PATH,
    DEFAULT_COMMUNITY_STATE_PATH,
    DEFAULT_COMMUNITY_TELEMETRY_DIR,
    DEFAULT_COMMUNITY_RUNTIME_PATH,
    DEFAULT_COMMUNITY_TELEMETRY_INTERVAL,
    DEFAULT_COMMUNITY_TELEMETRY_MAX_FRAMES,
    DEFAULT_EVENT_LOG_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    DEFAULT_REAL_TELEMETRY_STALE_SECONDS,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the complete LD6002C community classroom demo.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument(
        "--enable-ai",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use local Ollama for NORMAL/FALL demo actions (default: enabled).",
    )
    parser.add_argument("--ollama-base-url", default=DEFAULT_OLLAMA_BASE_URL)
    parser.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument("--ollama-timeout", type=float, default=DEFAULT_OLLAMA_TIMEOUT)
    parser.add_argument(
        "--audio-alarm",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--alarm-sound", type=Path, default=DEFAULT_ALARM_SOUND_PATH)
    parser.add_argument("--alarm-volume", type=int, default=DEFAULT_ALARM_VOLUME)
    parser.add_argument(
        "--open-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--config-path", type=Path, default=DEFAULT_COMMUNITY_CONFIG_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_COMMUNITY_STATE_PATH)
    parser.add_argument("--event-path", type=Path, default=DEFAULT_COMMUNITY_EVENT_PATH)
    parser.add_argument(
        "--telemetry-dir",
        type=Path,
        default=DEFAULT_COMMUNITY_TELEMETRY_DIR,
    )
    parser.add_argument("--runtime-path", type=Path, default=DEFAULT_COMMUNITY_RUNTIME_PATH)
    parser.add_argument(
        "--telemetry-interval",
        type=float,
        default=DEFAULT_COMMUNITY_TELEMETRY_INTERVAL,
    )
    parser.add_argument(
        "--telemetry-max-frames",
        type=int,
        default=DEFAULT_COMMUNITY_TELEMETRY_MAX_FRAMES,
    )
    parser.add_argument(
        "--real-stale-seconds",
        type=float,
        default=DEFAULT_REAL_TELEMETRY_STALE_SECONDS,
    )
    parser.add_argument("--real-log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset community demo state and exit without starting Streamlit.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        _validate_args(args)
        root = _find_project_root()
        controller = CommunityController.from_paths(
            args.config_path,
            args.state_path,
            args.event_path,
        )
        telemetry = CommunityTelemetryStore(
            args.telemetry_dir,
            max_frames=args.telemetry_max_frames,
        )
        health_store = CommunityRuntimeHealthStore(args.runtime_path)
        if args.reset:
            removed_events = controller.reset_demo_state()
            telemetry.clear()
            health_store.clear()
            print(
                "Community demo reset complete: "
                f"removed {removed_events} demo event(s) and all demo telemetry."
            )
            return

        if not _port_available(args.host, args.port):
            raise RuntimeError(
                f"Dashboard port {args.port} is already in use. "
                "Stop the old Streamlit process or choose --port PORT."
            )
        ai = (
            OllamaFallAI(
                base_url=args.ollama_base_url,
                model=args.ollama_model,
                timeout=args.ollama_timeout,
            )
            if args.enable_ai
            else None
        )
        alarm = (
            DesktopAudioAlarm(args.alarm_sound, volume=args.alarm_volume)
            if args.audio_alarm
            else ConsoleAlarm()
        )
        runtime = CommunityDemoRuntime(
            controller,
            telemetry,
            health_store,
            ai=ai,
            alarm=alarm,
            interval_seconds=args.telemetry_interval,
            real_log_path=args.real_log_path,
            real_stale_seconds=args.real_stale_seconds,
        )
        process: subprocess.Popen[bytes] | None = None
        try:
            runtime.start()
            ollama_status = _report_ai_status(args)
            env = _build_environment(args)
            command = [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(root / "dashboard" / "app.py"),
                "--server.address",
                args.host,
                "--server.port",
                str(args.port),
                "--server.headless",
                "true",
            ]
            process = subprocess.Popen(command, cwd=root, env=env)
            local_url = f"http://127.0.0.1:{args.port}"
            if not _wait_for_dashboard(local_url, process):
                raise RuntimeError("Streamlit did not become ready within 30 seconds.")
            _print_ready_urls(
                local_url,
                args.host,
                args.port,
                ollama_status=ollama_status,
                model=args.ollama_model,
                community_name=controller.registry.community_name,
                resident_count=len(controller.registry.residents),
            )
            if args.open_browser:
                webbrowser.open(local_url)
            process.wait()
        except KeyboardInterrupt:
            print("\nStopping community demo...")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            runtime.stop()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Community demo failed: {exc}") from exc


def _validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not 0 <= args.alarm_volume <= 100:
        raise ValueError("alarm volume must be between 0 and 100")
    if args.ollama_timeout <= 0:
        raise ValueError("ollama timeout must be greater than 0")
    if args.telemetry_interval <= 0:
        raise ValueError("telemetry interval must be greater than 0")
    if args.telemetry_max_frames < 1:
        raise ValueError("telemetry max frames must be positive")
    if args.real_stale_seconds <= 0:
        raise ValueError("real telemetry freshness must be greater than 0")


def _find_project_root() -> Path:
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / "dashboard" / "app.py").is_file():
            return candidate
    raise RuntimeError(
        "dashboard/app.py was not found. Run ld6002c-community-demo from the project directory."
    )


def _report_ai_status(args: argparse.Namespace) -> str:
    if not args.enable_ai:
        print("[AI] disabled; radar result pass-through will be used.")
        return "DISABLED"
    print("[AI] Ollama health check is running in the background.")
    return "CHECKING"


def _build_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AI_ENABLED": str(args.enable_ai).lower(),
            "OLLAMA_BASE_URL": args.ollama_base_url,
            "OLLAMA_MODEL": args.ollama_model,
            "OLLAMA_TIMEOUT": str(args.ollama_timeout),
            "AUDIO_ALARM_ENABLED": str(args.audio_alarm).lower(),
            "ALARM_SOUND_PATH": str(args.alarm_sound.resolve()),
            "ALARM_VOLUME": str(args.alarm_volume),
            "LD6002C_COMMUNITY_CONFIG_PATH": str(args.config_path.resolve()),
            "LD6002C_COMMUNITY_STATE_PATH": str(args.state_path.resolve()),
            "LD6002C_COMMUNITY_EVENT_PATH": str(args.event_path.resolve()),
            "LD6002C_COMMUNITY_TELEMETRY_DIR": str(args.telemetry_dir.resolve()),
            "LD6002C_COMMUNITY_RUNTIME_PATH": str(args.runtime_path.resolve()),
            "COMMUNITY_TELEMETRY_MAX_FRAMES": str(args.telemetry_max_frames),
            "REAL_TELEMETRY_STALE_SECONDS": str(args.real_stale_seconds),
            "LD6002C_LOG_PATH": str(args.real_log_path.resolve()),
            "LD6002C_EVENT_LOG_PATH": str(DEFAULT_EVENT_LOG_PATH.resolve()),
        }
    )
    return env


def _port_available(host: str, port: int) -> bool:
    bind_host = "0.0.0.0" if host in {"0.0.0.0", "::"} else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            # Match the server's reusable-listener behavior so recently closed
            # demo connections in TIME_WAIT do not look like a live process.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((bind_host, port))
    except OSError:
        return False
    return True


def _wait_for_dashboard(url: str, process: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Streamlit exited during startup with code {process.returncode}."
            )
        try:
            with urlopen(f"{url}/_stcore/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except (URLError, OSError):
            time.sleep(0.25)
    return False


def _print_ready_urls(
    local_url: str,
    host: str,
    port: int,
    *,
    ollama_status: str,
    model: str,
    community_name: str,
    resident_count: int,
) -> None:
    print("\n========================================")
    print(" Community Fall Detection Demo")
    print("========================================\n")
    print(f"Ollama      : {ollama_status}")
    print(f"Model       : {model}")
    print(f"Community   : {community_name}")
    print(f"Residents   : {resident_count}")
    print(f"Dashboard   : {local_url}/")
    print(f"Demo Control: {local_url}/?view=control")
    print(f"Technical   : {local_url}/?view=technical&resident=B2-302")
    if host in {"0.0.0.0", "::"}:
        lan_ip = _local_ip()
        if lan_ip:
            print(f"Mobile      : http://{lan_ip}:{port}/?view=control")
    print("\nREADY FOR DEMO")
    print("Press Ctrl+C to stop.\n")


def _local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
    except OSError:
        return None


if __name__ == "__main__":
    main()
