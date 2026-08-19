from __future__ import annotations

import csv
from datetime import datetime

from ld6002c_fall.ai.models import FallAIResult
from ld6002c_fall.logger import CSVFrameLogger
from ld6002c_fall.radar_model import RadarFrame, RadarPoint


def test_frame_logger_writes_ai_chain_fields(tmp_path) -> None:
    log_path = tmp_path / "fall_log.csv"
    logger = CSVFrameLogger(log_path)
    frame = RadarFrame(
        timestamp=datetime(2026, 8, 15, 14, 30, 0),
        human_present=True,
        fall_detected=True,
        motion_state="still",
        raw="55 01 00 01 0e 02 00",
        points=(RadarPoint(3, -0.2, 1.1, 0.4, -0.05),),
    )
    ai_result = FallAIResult(
        result=1,
        label="FALL",
        message="毫米波雷达检测到跌倒状态。",
        model="qwen3:0.6b",
        inference_ms=182.4,
        success=True,
    )

    logger.log(frame, "观察中", "serial", ai_result)

    with log_path.open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert row["radar_is_fall"] == "1"
    assert row["ai_result"] == "1"
    assert row["ai_status"] == "AI_SUCCESS"
    assert row["ai_cached"] == "False"
    assert row["ai_model"] == "qwen3:0.6b"
    assert row["final_result"] == "1"
    assert row["point_count"] == "1"
    assert row["radar_points"] == (
        '[{"cluster_id":3,"x":-0.2,"y":1.1,"z":0.4,"speed":-0.05}]'
    )


def test_frame_logger_migrates_pre_ai_log(tmp_path) -> None:
    log_path = tmp_path / "fall_log.csv"
    log_path.write_text(
        "timestamp,source,human_present,fall_detected,motion_state,system_state,raw\n"
        "2026-08-15T14:30:00,serial,True,True,unknown,观察中,frame hex\n",
        encoding="utf-8",
    )

    CSVFrameLogger(log_path)

    with log_path.open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert row["radar_is_fall"] == "1"
    assert row["ai_result"] == "1"
    assert row["ai_status"] == "AI_LEGACY"
    assert row["ai_success"] == "False"
    assert row["ai_cached"] == "False"
    assert row["ai_model"] == "legacy"
    assert row["final_result"] == "1"
    assert row["point_count"] == "0"
    assert row["radar_points"] == "[]"


def test_frame_logger_migrates_pre_cache_ai_log(tmp_path) -> None:
    log_path = tmp_path / "fall_log.csv"
    rows = [
        {
            "timestamp": f"2026-08-15T14:30:0{index}",
            "source": "mock",
            "human_present": "True",
            "fall_detected": "False",
            "motion_state": "moving",
            "system_state": "正常有人",
            "raw": f"mock:{index}",
            "radar_is_fall": "0",
            "ai_result": "0",
            "ai_label": "NORMAL",
            "ai_status": "AI_SUCCESS",
            "ai_success": "True",
            "ai_model": "qwen3:0.6b",
            "ai_inference_ms": "123.4",
            "ai_message": "正常",
            "final_result": "0",
        }
        for index in range(2)
    ]
    with log_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSVFrameLogger.pre_cache_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    CSVFrameLogger(log_path)

    with log_path.open(newline="", encoding="utf-8") as file:
        migrated = list(csv.DictReader(file))
    assert migrated[0]["ai_cached"] == "False"
    assert migrated[1]["ai_cached"] == "True"
    assert migrated[0]["ai_status"] == "AI_SUCCESS"
