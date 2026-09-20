from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError

from dashboard.app import (
    EVENT_LOG_PATH,
    LOG_PATH,
    _route_from_query_params,
    _technical_data_paths,
)
from ld6002c_fall.ai import OllamaFallAI
from ld6002c_fall.alarm import AlarmOutput
from ld6002c_fall.community import (
    CommunityController,
    CommunityRegistry,
    CommunityTelemetryStore,
    DemoControlService,
    latest_alarm_resident_id,
)
from ld6002c_fall.live_monitor import build_monitor_snapshot, build_point_history
from ld6002c_fall.radar_model import RadarFrame


ROOT = Path(__file__).resolve().parents[1]
BASE = datetime(2026, 9, 20, 12, 0, tzinfo=timezone(timedelta(hours=8)))


def make_controller(tmp_path: Path) -> CommunityController:
    return CommunityController.from_paths(
        ROOT / "config" / "community.json",
        tmp_path / "community_state.json",
        tmp_path / "community_events.csv",
    )


def read_events(tmp_path: Path) -> list[dict[str, str]]:
    with (tmp_path / "community_events.csv").open(
        newline="",
        encoding="utf-8",
    ) as file:
        return list(csv.DictReader(file))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


class RecordingAlarm(AlarmOutput):
    def __init__(self) -> None:
        self.emitted: list[tuple[RadarFrame, str]] = []
        self.close_count = 0

    def emit(self, frame: RadarFrame, state: str) -> None:
        self.emitted.append((frame, state))

    def close(self) -> None:
        self.close_count += 1


def test_registry_loads_18_residents_and_real_sensor_binding() -> None:
    registry = CommunityRegistry.load(ROOT / "config" / "community.json")

    assert registry.community_name == "幸福社区"
    assert len(registry.residents) == 18
    assert registry.bound_to("LD6002C").id == "B2-302"
    assert registry.get("B2-302").name == "王阿姨"


def test_state_store_initializes_every_resident_and_persists_json(tmp_path) -> None:
    controller = make_controller(tmp_path)
    states = controller.states()

    assert len(states) == 18
    assert {state.status for state in states.values()} == {"NORMAL"}
    payload = json.loads((tmp_path / "community_state.json").read_text(encoding="utf-8"))
    assert payload["community_name"] == "幸福社区"
    assert len(payload["residents"]) == 18
    assert not list(tmp_path.glob("*.tmp"))


def test_real_sensor_maps_confirmed_fall_to_b2_302_and_logs_event(tmp_path) -> None:
    controller = make_controller(tmp_path)

    state = controller.update_from_sensor(
        "B2-302",
        radar_result=1,
        ai_result=1,
        device_state="CONFIRMED_FALL",
        timestamp=BASE,
        ai_model="qwen3:0.6b",
        ai_success=True,
        source="LD6002C:serial",
    )

    assert state.status == "FALL"
    assert state.alarm_time == BASE
    assert state.radar_result == state.ai_result == 1
    events = read_events(tmp_path)
    assert events[-1]["event"] == "FALL_ALERT"
    assert events[-1]["resident_id"] == "B2-302"
    assert events[-1]["source"] == "LD6002C:serial"


def test_demo_injection_supports_fall_acknowledge_offline_and_recovery(tmp_path) -> None:
    controller = make_controller(tmp_path)

    falling = controller.inject_demo(
        "B1-101",
        "FALL",
        timestamp=BASE,
        radar_result=1,
        ai_result=1,
        ai_model="qwen3:0.6b",
        ai_success=True,
        source="DEMO_AI",
    )
    acknowledged = controller.acknowledge_alarm(
        "B1-101",
        timestamp=BASE + timedelta(seconds=1),
    )
    offline = controller.inject_demo(
        "B1-102",
        "OFFLINE",
        timestamp=BASE + timedelta(seconds=2),
    )
    recovered = controller.recover(
        "B1-102",
        timestamp=BASE + timedelta(seconds=3),
    )

    assert falling.status == "FALL" and falling.demo_override is True
    assert acknowledged.status == "FALL" and acknowledged.handled is True
    assert offline.status == "OFFLINE"
    assert recovered.status == "NORMAL" and recovered.demo_override is False
    names = [event["event"] for event in read_events(tmp_path)]
    assert "DEMO_INJECTED" in names
    assert "FALL_ALERT" in names
    assert "ALERT_ACKNOWLEDGED" in names
    assert "DEVICE_OFFLINE" in names
    assert "DEVICE_ONLINE" in names
    assert "RECOVERED" in names


def test_demo_override_is_not_replaced_by_live_sensor_until_recovered(tmp_path) -> None:
    controller = make_controller(tmp_path)
    controller.inject_demo("B2-302", "FALL", timestamp=BASE, source="DEMO")

    still_demo = controller.update_from_sensor(
        "B2-302",
        radar_result=0,
        ai_result=0,
        device_state="NORMAL",
        timestamp=BASE + timedelta(seconds=1),
        source="LD6002C:serial",
    )
    controller.recover("B2-302", timestamp=BASE + timedelta(seconds=2))
    live_again = controller.update_from_sensor(
        "B2-302",
        radar_result=0,
        ai_result=0,
        device_state="NORMAL",
        timestamp=BASE + timedelta(seconds=3),
        source="LD6002C:serial",
    )

    assert still_demo.status == "FALL"
    assert still_demo.source == "DEMO"
    assert live_again.status == "NORMAL"
    assert live_again.source == "LD6002C:serial"


def test_latest_alarm_prefers_newest_unhandled_resident(tmp_path) -> None:
    controller = make_controller(tmp_path)
    controller.inject_demo("B1-101", "FALL", timestamp=BASE)
    controller.inject_demo("B3-102", "FALL", timestamp=BASE + timedelta(seconds=5))

    assert latest_alarm_resident_id(controller.states()) == "B3-102"

    controller.acknowledge_alarm("B3-102", timestamp=BASE + timedelta(seconds=6))
    assert latest_alarm_resident_id(controller.states()) == "B1-101"


def test_demo_fall_passes_through_real_ai_bridge_contract(tmp_path) -> None:
    calls: list[int] = []

    def transport(_url: str, payload: dict[str, Any] | None, _timeout: float) -> dict[str, Any]:
        assert payload is not None
        content = str(payload["messages"][-1]["content"])
        is_fall = int(content.rsplit("=", 1)[-1].strip())
        calls.append(is_fall)
        return {
            "model": "qwen3:0.6b",
            "message": {
                "content": f'{{"result":{is_fall},"label":"FALL","message":"demo"}}'
            },
        }

    controller = make_controller(tmp_path)
    service = DemoControlService(controller, OllamaFallAI(transport=transport))
    result = service.execute("B3-201", "FALL", timestamp=BASE)

    assert calls == [1]
    assert result.ai_result is not None and result.ai_result.success is True
    assert result.source == "DEMO_AI"
    assert result.state.status == "FALL"
    assert result.state.ai_model == "qwen3:0.6b"


def test_demo_normal_passes_through_ai_and_recovers_resident(tmp_path) -> None:
    def transport(_url: str, payload: dict[str, Any] | None, _timeout: float) -> dict[str, Any]:
        assert payload is not None
        content = str(payload["messages"][-1]["content"])
        is_fall = int(content.rsplit("=", 1)[-1].strip())
        label = "FALL" if is_fall else "NORMAL"
        return {
            "model": "qwen3:0.6b",
            "message": {
                "content": f'{{"result":{is_fall},"label":"{label}","message":"demo"}}'
            },
        }

    controller = make_controller(tmp_path)
    controller.inject_demo("B1-201", "FALL", timestamp=BASE)
    service = DemoControlService(controller, OllamaFallAI(transport=transport))
    result = service.execute(
        "B1-201",
        "NORMAL",
        timestamp=BASE + timedelta(seconds=1),
    )

    assert result.ai_result is not None and result.ai_result.result == 0
    assert result.state.status == "NORMAL"
    assert result.state.demo_override is True
    assert "RECOVERED" in [event["event"] for event in read_events(tmp_path)]


def test_demo_ai_failure_is_explicitly_logged_as_fallback(tmp_path) -> None:
    def unavailable(_url: str, _payload: dict[str, Any] | None, _timeout: float):
        raise URLError("offline")

    controller = make_controller(tmp_path)
    service = DemoControlService(controller, OllamaFallAI(transport=unavailable))
    result = service.execute("B3-202", "FALL", timestamp=BASE)

    assert result.ai_result is not None and result.ai_result.success is False
    assert result.source == "AI_FALLBACK"
    assert result.state.status == "FALL"
    assert read_events(tmp_path)[-1]["source"] == "AI_FALLBACK"


def test_query_parameter_routes_do_not_depend_on_session_navigation() -> None:
    assert _route_from_query_params({}) == ("community", None)
    assert _route_from_query_params({"view": "control"}) == ("control", None)
    assert _route_from_query_params(
        {"view": "technical", "resident": "B2-302"}
    ) == ("technical", "B2-302")
    assert _route_from_query_params({"view": "unknown"}) == ("community", None)
    assert "segmented_control" not in (ROOT / "dashboard" / "app.py").read_text(
        encoding="utf-8"
    )


def test_fall_demo_writes_ai_telemetry_and_triggers_alarm_once(tmp_path) -> None:
    calls: list[int] = []

    def transport(_url: str, payload: dict[str, Any] | None, _timeout: float):
        assert payload is not None
        calls.append(1)
        return {
            "model": "qwen3:0.6b",
            "message": {"content": '{"result":1,"label":"FALL","message":"confirmed"}'},
        }

    controller = make_controller(tmp_path)
    telemetry = CommunityTelemetryStore(tmp_path / "telemetry")
    alarm = RecordingAlarm()
    service = DemoControlService(
        controller,
        OllamaFallAI(transport=transport),
        telemetry,
        alarm,
    )

    first = service.execute("B1-101", "FALL", timestamp=BASE)
    repeated = service.execute("B1-101", "FALL", timestamp=BASE + timedelta(seconds=1))

    frames = read_csv(telemetry.frame_path("B1-101"))
    events = read_csv(telemetry.event_path("B1-101"))
    assert first.alarm_triggered is True
    assert repeated.alarm_triggered is False
    assert calls == [1, 1]
    assert len(alarm.emitted) == 1
    assert len(frames) == 30
    assert all(row["resident_id"] == "B1-101" for row in frames)
    assert all(row["source"] == "community_demo" for row in frames)
    assert all(int(row["point_count"]) > 0 for row in frames)
    assert {row["event"] for row in events} >= {
        "AI_REQUEST",
        "AI_RESPONSE",
        "FALL_DETECTED",
        "ALARM_TRIGGERED",
    }
    assert sum(row["event"] == "ALARM_TRIGGERED" for row in events) == 1


def test_recover_closes_alarm_and_replaces_cloud_with_normal_shape(tmp_path) -> None:
    controller = make_controller(tmp_path)
    telemetry = CommunityTelemetryStore(tmp_path / "telemetry")
    alarm = RecordingAlarm()
    service = DemoControlService(controller, None, telemetry, alarm)

    service.execute("B3-302", "FALL", timestamp=BASE)
    result = service.execute("B3-302", "RECOVER", timestamp=BASE + timedelta(seconds=1))

    rows = read_csv(telemetry.frame_path("B3-302"))
    points = json.loads(rows[-1]["radar_points"])
    assert result.state.status == "NORMAL"
    assert result.state.demo_override is False
    assert alarm.close_count == 1
    assert len(rows) == 30
    assert max(point["z"] for point in points) > 1.5
    assert max(point["x"] for point in points) - min(point["x"] for point in points) < 0.2


def test_offline_demo_has_no_point_cloud_and_reports_disconnected(tmp_path) -> None:
    controller = make_controller(tmp_path)
    telemetry = CommunityTelemetryStore(tmp_path / "telemetry")
    service = DemoControlService(controller, None, telemetry, RecordingAlarm())

    service.execute("B2-101", "NORMAL", timestamp=BASE)
    service.execute("B2-101", "OFFLINE", timestamp=BASE + timedelta(seconds=1))

    rows = read_csv(telemetry.frame_path("B2-101"))
    events = read_csv(telemetry.event_path("B2-101"))
    snapshot = build_monitor_snapshot(
        rows,
        events,
        now=BASE + timedelta(seconds=1),
    )
    assert len(rows) == 1
    assert rows[0]["device_state"] == "DISCONNECTED"
    assert rows[0]["radar_points"] == "[]"
    assert build_point_history(rows) == []
    assert snapshot.radar_status == "DISCONNECTED"


def test_community_demo_snapshot_stays_connected_until_explicit_offline(tmp_path) -> None:
    controller = make_controller(tmp_path)
    telemetry = CommunityTelemetryStore(tmp_path / "telemetry")
    service = DemoControlService(controller, None, telemetry, RecordingAlarm())
    service.execute("B2-102", "NORMAL", timestamp=BASE)
    rows = read_csv(telemetry.frame_path("B2-102"))

    snapshot = build_monitor_snapshot(
        rows,
        [],
        now=BASE + timedelta(hours=2),
    )

    assert snapshot.radar_status == "CONNECTED"
    assert snapshot.current_status == "NORMAL"


def test_technical_detail_uses_demo_files_for_simulated_or_overridden_resident(
    tmp_path,
) -> None:
    controller = make_controller(tmp_path)
    telemetry = CommunityTelemetryStore(tmp_path / "telemetry")

    simulated = _technical_data_paths(controller, "B1-101", telemetry)
    real = _technical_data_paths(controller, "B2-302", telemetry)
    controller.inject_demo("B2-302", "FALL", timestamp=BASE)
    overridden = _technical_data_paths(controller, "B2-302", telemetry)

    assert simulated == (
        telemetry.frame_path("B1-101"),
        telemetry.event_path("B1-101"),
        "SIMULATED RADAR DATA · CLASSROOM DEMO",
        True,
    )
    assert real == (LOG_PATH, EVENT_LOG_PATH, "HLK-LD6002C · REALTIME", False)
    assert overridden[0] == telemetry.frame_path("B2-302")
    assert overridden[3] is True
