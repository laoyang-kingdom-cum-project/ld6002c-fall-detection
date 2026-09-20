from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError

from dashboard.community_ui import resident_supports_technical_detail
from ld6002c_fall.ai import OllamaFallAI
from ld6002c_fall.community import (
    CommunityController,
    CommunityRegistry,
    DemoControlService,
    latest_alarm_resident_id,
)


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


def test_simulated_residents_never_claim_live_technical_telemetry() -> None:
    registry = CommunityRegistry.load(ROOT / "config" / "community.json")

    assert resident_supports_technical_detail(registry.get("B2-302")) is True
    assert resident_supports_technical_detail(registry.get("B1-101")) is False
