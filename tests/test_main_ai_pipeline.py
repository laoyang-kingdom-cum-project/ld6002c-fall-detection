from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ld6002c_fall.ai import AIInferenceScheduler, OllamaFallAI
from ld6002c_fall.alarm import ConsoleAlarm
from ld6002c_fall.community import CommunityController
from ld6002c_fall.event_logger import CSVEventLogger
from ld6002c_fall.fall_detector import FallDetector
from ld6002c_fall.logger import CSVFrameLogger
from ld6002c_fall.main import RuntimeServices, _process_frame
from ld6002c_fall.radar_model import RadarFrame
from ld6002c_fall.system_controller import SystemController


BASE = datetime(2026, 8, 15, 12, 0, 0)
ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_calls_ai_on_both_signal_edges_and_logs_events(tmp_path) -> None:
    calls: list[int] = []

    def transport(_url: str, payload: dict[str, Any] | None, _timeout: float) -> dict[str, Any]:
        assert payload is not None
        content = str(payload["messages"][-1]["content"])
        is_fall = int(content.rsplit("=", 1)[-1].strip())
        calls.append(is_fall)
        label = "FALL" if is_fall else "NORMAL"
        return {
            "model": "qwen3:0.6b",
            "message": {"content": f'{{"result":{is_fall},"label":"{label}"}}'},
        }

    runtime = RuntimeServices(
        detector=FallDetector(suspect_seconds=0, confirm_seconds=0),
        frame_logger=CSVFrameLogger(tmp_path / "frames.csv"),
        event_logger=CSVEventLogger(tmp_path / "events.csv"),
        alarm=ConsoleAlarm(),
        controller=SystemController(),
        ai=OllamaFallAI(transport=transport),
        ai_scheduler=AIInferenceScheduler(periodic_interval=3),
    )

    for seconds, is_fall in [(0, False), (1, False), (1.1, True), (1.2, False)]:
        _process_frame(
            RadarFrame(
                timestamp=BASE + timedelta(seconds=seconds),
                human_present=True,
                fall_detected=is_fall,
                motion_state="still" if is_fall else "moving",
                raw=f"raw:{int(is_fall)}",
            ),
            runtime,
            "mock",
        )

    assert calls == [0, 1, 0]
    with (tmp_path / "events.csv").open(newline="", encoding="utf-8") as file:
        events = [row["event"] for row in csv.DictReader(file)]
    assert events.count("AI_REQUEST") == 3
    assert events.count("AI_RESPONSE") == 3
    assert "FALL_DETECTED" in events
    assert "ALARM_TRIGGERED" in events


def test_serial_pipeline_updates_bound_community_resident(tmp_path) -> None:
    community = CommunityController.from_paths(
        ROOT / "config" / "community.json",
        tmp_path / "community_state.json",
        tmp_path / "community_events.csv",
    )
    runtime = RuntimeServices(
        detector=FallDetector(suspect_seconds=0, confirm_seconds=0),
        frame_logger=CSVFrameLogger(tmp_path / "frames.csv"),
        event_logger=CSVEventLogger(tmp_path / "events.csv"),
        alarm=ConsoleAlarm(),
        controller=SystemController(),
        community_controller=community,
        community_resident_id="B2-302",
    )

    _process_frame(
        RadarFrame(
            timestamp=BASE,
            human_present=True,
            fall_detected=True,
            motion_state="still",
            raw="serial:confirmed-fall",
        ),
        runtime,
        "serial",
    )

    state = community.states()["B2-302"]
    assert state.status == "FALL"
    assert state.radar_result == state.ai_result == 1
    assert state.source == "LD6002C:serial"
