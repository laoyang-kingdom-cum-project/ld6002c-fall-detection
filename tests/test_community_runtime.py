from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError

import dashboard.app as dashboard_app
from ld6002c_fall.ai import OllamaFallAI
from ld6002c_fall.alarm import AlarmOutput
from ld6002c_fall.community import (
    CommunityController,
    CommunityDemoRuntime,
    CommunityRuntimeHealthStore,
    CommunityTelemetryStore,
    DemoControlService,
)
from ld6002c_fall.radar_model import RadarFrame


ROOT = Path(__file__).resolve().parents[1]
BASE = datetime(2026, 9, 21, 8, 0, tzinfo=timezone(timedelta(hours=8)))


class RecordingAlarm(AlarmOutput):
    def __init__(self) -> None:
        self.emitted: list[RadarFrame] = []
        self.closed = 0

    def emit(self, frame: RadarFrame, state: str) -> None:
        assert state == "确认跌倒"
        self.emitted.append(frame)

    def close(self) -> None:
        self.closed += 1


def _runtime(
    tmp_path: Path,
    *,
    max_frames: int = 60,
    ai: OllamaFallAI | None = None,
    alarm: AlarmOutput | None = None,
) -> tuple[CommunityController, CommunityTelemetryStore, CommunityDemoRuntime]:
    controller = CommunityController.from_paths(
        ROOT / "config" / "community.json",
        tmp_path / "community_state.json",
        tmp_path / "community_events.csv",
    )
    telemetry = CommunityTelemetryStore(
        tmp_path / "community_telemetry",
        max_frames=max_frames,
    )
    runtime = CommunityDemoRuntime(
        controller,
        telemetry,
        CommunityRuntimeHealthStore(tmp_path / "community_runtime.json"),
        ai=ai,
        alarm=alarm,
        interval_seconds=0.5,
    )
    return controller, telemetry, runtime


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_first_runtime_tick_prewarms_all_residents_without_buttons(tmp_path) -> None:
    controller, telemetry, runtime = _runtime(tmp_path)

    runtime.tick(BASE)

    assert len(controller.registry.residents) == 18
    for resident in controller.registry.residents:
        rows = _rows(telemetry.frame_path(resident.id))
        assert rows[-1]["device_state"] == "NORMAL"
        assert rows[-1]["human_present"] == "True"
        assert int(rows[-1]["point_count"]) > 0


def test_demo_control_only_requests_scenario_and_does_not_write_telemetry(tmp_path) -> None:
    controller, telemetry, _ = _runtime(tmp_path)

    result = DemoControlService(controller).execute("B1-101", "FALL", timestamp=BASE)

    assert result.state.status == "NORMAL"
    assert result.state.desired_scenario == "FALL"
    assert result.state.scenario_revision == 1
    assert not telemetry.frame_path("B1-101").exists()
    source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    assert "telemetry.write_scenario" not in source


def test_runtime_keeps_bounded_timestamped_history(tmp_path) -> None:
    _, telemetry, runtime = _runtime(tmp_path, max_frames=3)

    for index in range(6):
        runtime.tick(BASE + timedelta(seconds=index * 0.5))

    rows = _rows(telemetry.frame_path("B1-102"))
    timestamps = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    assert len(rows) == 3
    assert timestamps == sorted(timestamps)
    assert timestamps[-1] > timestamps[0]


def test_fall_and_recovery_append_without_rewriting_history(tmp_path) -> None:
    controller, telemetry, runtime = _runtime(tmp_path)
    control = DemoControlService(controller)
    runtime.tick(BASE)

    control.execute("B1-201", "FALL", timestamp=BASE + timedelta(seconds=0.5))
    runtime.tick(BASE + timedelta(seconds=0.5))
    control.execute("B1-201", "RECOVER", timestamp=BASE + timedelta(seconds=1))
    runtime.tick(BASE + timedelta(seconds=1))

    rows = _rows(telemetry.frame_path("B1-201"))
    statuses = [row["raw"].split("status=", 1)[1].split(";", 1)[0] for row in rows]
    assert statuses == ["NORMAL", "FALL", "NORMAL"]
    state = controller.states()["B1-201"]
    assert state.status == "NORMAL"
    assert state.demo_override is False


def test_offline_appends_disconnect_once_and_stops_new_frames(tmp_path) -> None:
    controller, telemetry, runtime = _runtime(tmp_path)
    runtime.tick(BASE)
    DemoControlService(controller).execute("B2-101", "OFFLINE", timestamp=BASE)
    runtime.tick(BASE + timedelta(seconds=0.5))
    count = len(_rows(telemetry.frame_path("B2-101")))

    runtime.tick(BASE + timedelta(seconds=1))

    rows = _rows(telemetry.frame_path("B2-101"))
    assert len(rows) == count
    assert rows[-1]["device_state"] == "DISCONNECTED"
    assert rows[-1]["radar_points"] == "[]"


def test_ai_offline_keeps_business_result_and_records_control_health(tmp_path) -> None:
    def offline(_url: str, _payload: dict[str, Any] | None, _timeout: float):
        raise URLError("offline")

    ai = OllamaFallAI(transport=offline)
    controller, telemetry, runtime = _runtime(tmp_path, ai=ai)
    runtime.tick(BASE)
    runtime.refresh_ai_health()
    DemoControlService(controller).execute("B3-101", "FALL", timestamp=BASE)
    runtime.tick(BASE + timedelta(seconds=0.5))

    rows = _rows(telemetry.frame_path("B3-101"))
    events = _rows(telemetry.event_path("B3-101"))
    health = runtime.health_store.read()
    assert rows[-1]["final_result"] == "1"
    assert int(rows[-1]["point_count"]) > 0
    assert {row["event"] for row in events} >= {"AI_ERROR", "AI_FALLBACK"}
    assert health.ollama == "OFFLINE"
    assert health.ai_mode == "FALLBACK"


def test_real_telemetry_requires_fresh_last_timestamp(tmp_path, monkeypatch) -> None:
    controller, telemetry, _ = _runtime(tmp_path)
    real_log = tmp_path / "fall_log.csv"
    real_log.write_text(
        "timestamp,human_present\n"
        f"{(BASE - timedelta(seconds=30)).isoformat()},True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "LOG_PATH", real_log)

    stale = dashboard_app._technical_data_paths(
        controller,
        "B2-302",
        telemetry,
        now=BASE,
        real_stale_seconds=5,
    )
    real_log.write_text(
        "timestamp,human_present\n"
        f"{(BASE - timedelta(seconds=2)).isoformat()},True\n",
        encoding="utf-8",
    )
    fresh = dashboard_app._technical_data_paths(
        controller,
        "B2-302",
        telemetry,
        now=BASE,
        real_stale_seconds=5,
    )

    assert stale[0] == telemetry.frame_path("B2-302") and stale[3] is True
    assert fresh[0] == real_log and fresh[3] is False


def test_fall_alarm_is_emitted_once_per_transition(tmp_path) -> None:
    alarm = RecordingAlarm()
    controller, _, runtime = _runtime(tmp_path, alarm=alarm)
    control = DemoControlService(controller)
    runtime.tick(BASE)

    control.execute("B3-202", "FALL", timestamp=BASE + timedelta(seconds=0.5))
    runtime.tick(BASE + timedelta(seconds=0.5))
    control.execute("B3-202", "FALL", timestamp=BASE + timedelta(seconds=1))
    runtime.tick(BASE + timedelta(seconds=1))
    control.execute("B3-202", "RECOVER", timestamp=BASE + timedelta(seconds=1.5))
    runtime.tick(BASE + timedelta(seconds=1.5))
    control.execute("B3-202", "FALL", timestamp=BASE + timedelta(seconds=2))
    runtime.tick(BASE + timedelta(seconds=2))

    assert len(alarm.emitted) == 2
    assert alarm.closed >= 1
