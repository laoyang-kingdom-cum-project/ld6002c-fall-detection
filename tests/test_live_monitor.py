from __future__ import annotations

from datetime import datetime

import pytest

from ld6002c_fall.live_monitor import (
    build_axis_history,
    build_ai_chat,
    build_monitor_snapshot,
    build_point_history,
    build_sensor_stream,
    point_cloud_status,
)


NOW = datetime.fromisoformat("2026-08-15T12:00:01+08:00")


def frame(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": "2026-08-15T12:00:00.000+08:00",
        "source": "serial",
        "human_present": True,
        "fall_detected": False,
        "radar_is_fall": 0,
        "final_result": 0,
        "motion_state": "moving",
        "device_state": "NORMAL",
        "ai_status": "AI_SUCCESS",
        "ai_work_state": "MONITORING",
        "ai_model": "qwen3:0.6b",
        "raw": "55 01 00",
    }
    row.update(overrides)
    return row


def event(name: str, details: str = "{}") -> dict[str, object]:
    return {
        "timestamp": "2026-08-15T12:00:00.100+08:00",
        "event": name,
        "details": details,
        "raw": "55 01 00",
    }


def test_monitor_reports_normal_and_fall_ai_results() -> None:
    normal = build_monitor_snapshot([frame()], [], now=NOW)
    falling = build_monitor_snapshot(
        [frame(final_result=1, device_state="CONFIRMED_FALL", ai_work_state="FALL_DETECTED")],
        [],
        now=NOW,
    )

    assert normal.current_status == "NORMAL"
    assert normal.radar_status == "CONNECTED"
    assert normal.source == "HLK-LD6002C"
    assert falling.current_status == "CONFIRMED_FALL"
    assert falling.fall_detected is True


def test_monitor_shows_analyzing_and_fallback() -> None:
    request = event(
        "AI_REQUEST",
        '{"is_fall":1,"trigger":"transition","model":"qwen3:0.6b"}',
    )
    analyzing = build_monitor_snapshot([frame()], [request], now=NOW)
    fallback = build_monitor_snapshot(
        [frame(ai_status="AI_FALLBACK", ai_work_state="FALLBACK")],
        [request, event("AI_ERROR", '{"message":"timeout"}'), event("AI_FALLBACK", '{"result":1,"message":"fallback"}')],
        now=NOW,
    )

    assert analyzing.current_status == "NORMAL"
    assert analyzing.ai_work_state == "ANALYZING"
    assert fallback.ollama_status == "FALLBACK"
    assert fallback.ai_work_state == "FALLBACK"


def test_monitor_exposes_ai_error_before_fallback_event() -> None:
    snapshot = build_monitor_snapshot(
        [frame()],
        [event("AI_REQUEST"), event("AI_ERROR", '{"message":"timeout"}')],
        now=NOW,
    )

    assert snapshot.ai_work_state == "ERROR"
    assert snapshot.ollama_status == "FALLBACK"


def test_monitor_expires_stale_radar_and_ai_status() -> None:
    snapshot = build_monitor_snapshot(
        [frame()],
        [event("AI_REQUEST")],
        now=datetime.fromisoformat("2026-08-15T12:01:00+08:00"),
    )

    assert snapshot.radar_status == "DISCONNECTED"
    assert snapshot.current_status == "DISCONNECTED"
    assert snapshot.ollama_status == "UNKNOWN"
    assert snapshot.ai_work_state == "MONITORING"


def test_monitor_ignores_an_expired_pending_ai_request() -> None:
    snapshot = build_monitor_snapshot(
        [frame(timestamp="2026-08-15T12:00:45+08:00")],
        [event("AI_REQUEST")],
        now=datetime.fromisoformat("2026-08-15T12:00:46+08:00"),
        ai_event_stale_seconds=30.0,
    )

    assert snapshot.current_status == "NORMAL"
    assert snapshot.ai_work_state == "MONITORING"


def test_monitor_tracks_sticks3_alarm_cancel_and_raw_stream() -> None:
    events = [
        event("DEVICE_CONNECTED"),
        event("FALL_DETECTED"),
        event("ALARM_TRIGGERED"),
        event("ALARM_CANCELLED"),
    ]
    snapshot = build_monitor_snapshot(
        [frame(device_state="CANCELLED", final_result=1)], events, now=NOW
    )
    stream = build_sensor_stream([frame()], events)
    chat = build_ai_chat(events)

    assert snapshot.sticks3_status == "CONNECTED"
    assert snapshot.current_status == "CANCELLED"
    assert any(item.category == "ALARM_TRIGGERED" for item in stream)
    assert any(item.category == "ALARM_CANCELLED" for item in stream)
    assert any(item.raw == "55 01 00" for item in stream)
    assert any(item.status == "ALARM_TRIGGERED" for item in chat)
    assert any(item.status == "ALARM_CANCELLED" for item in chat)


def test_ai_chat_uses_real_events_and_merges_periodic_normal_checks() -> None:
    events = []
    for _ in range(2):
        events.extend(
            [
                event("AI_REQUEST", '{"is_fall":0,"trigger":"periodic","model":"qwen3:0.6b"}'),
                event("AI_RESPONSE", '{"result":0,"label":"NORMAL","message":"正常","trigger":"periodic","model":"qwen3:0.6b","inference_ms":10.0}'),
            ]
        )
    events.append(event("AI_REQUEST", '{"is_fall":1,"trigger":"transition","model":"qwen3:0.6b"}'))

    chat = build_ai_chat(events)

    assert chat[0].status == "COMPLETED"
    assert chat[0].occurrences == 2
    assert chat[-1].status == "ANALYZING"
    assert chat[-1].is_fall == 1


def test_point_history_parses_coordinates_and_marks_latest_cloud() -> None:
    frames = [
        frame(
            timestamp="2026-08-15T12:00:00+08:00",
            radar_points='[{"cluster_id":1,"x":0.1,"y":1.2,"z":1.6,"speed":0.2}]',
        ),
        frame(
            timestamp="2026-08-15T12:00:01+08:00",
            radar_points='[{"cluster_id":2,"x":-0.2,"y":1.1,"z":0.4,"speed":-0.1}]',
        ),
    ]

    history = build_point_history(frames)

    assert len(history) == 2
    assert history[0].is_latest_cloud is False
    assert history[1].is_latest_cloud is True
    assert history[1].is_current is True
    assert history[1].x == -0.2


def test_axis_history_uses_one_centroid_sample_per_cloud_frame() -> None:
    history = build_point_history(
        [
            frame(
                timestamp="2026-08-15T12:00:00+08:00",
                radar_points=(
                    '[{"cluster_id":1,"x":0.0,"y":1.0,"z":0.2,"speed":-0.2},'
                    '{"cluster_id":2,"x":1.0,"y":2.0,"z":0.6,"speed":0.4}]'
                ),
            ),
            frame(
                timestamp="2026-08-15T12:00:01+08:00",
                radar_points=(
                    '[{"cluster_id":3,"x":0.4,"y":1.4,"z":0.8,"speed":0.1}]'
                ),
            ),
        ]
    )

    samples = build_axis_history(history)

    assert len(samples) == 2
    assert samples[0].x == 0.5
    assert samples[0].y == 1.5
    assert samples[0].z == 0.4
    assert samples[0].point_count == 2
    assert samples[0].mean_speed == pytest.approx(0.3)
    assert samples[1].timestamp == "2026-08-15T12:00:01+08:00"


def test_axis_history_keeps_only_latest_samples() -> None:
    frames = [
        frame(
            timestamp=f"2026-08-15T12:00:{second:02d}+08:00",
            radar_points=(
                f'[{{"cluster_id":{second},"x":{second},"y":1.0,'
                '"z":0.5,"speed":0.0}]'
            ),
        )
        for second in range(4)
    ]

    samples = build_axis_history(build_point_history(frames), max_samples=2)

    assert [sample.x for sample in samples] == [2.0, 3.0]


def test_point_cloud_status_uses_last_cloud_time_not_latest_status_frame() -> None:
    history = build_point_history(
        [
            frame(
                timestamp="2026-08-15T12:00:00+08:00",
                radar_points='[{"cluster_id":1,"x":0.1,"y":1.2,"z":1.6,"speed":0.2}]',
            ),
            frame(timestamp="2026-08-15T12:00:02+08:00", radar_points="[]"),
        ]
    )

    assert point_cloud_status(history, now=NOW, stale_seconds=2.0) == "TRACKING"
    assert (
        point_cloud_status(
            history,
            now=datetime.fromisoformat("2026-08-15T12:00:10+08:00"),
            stale_seconds=2.0,
        )
        == "STALE"
    )


def test_point_history_skips_non_finite_coordinates() -> None:
    history = build_point_history(
        [frame(radar_points='[{"cluster_id":1,"x":NaN,"y":1.2,"z":1.6,"speed":0.2}]')]
    )

    assert history == []


def test_status_frames_do_not_evict_a_recent_cloud_from_history() -> None:
    cloud = frame(
        radar_points='[{"cluster_id":1,"x":0.1,"y":1.2,"z":1.6,"speed":0.2}]'
    )
    status_frames = [frame(radar_points="[]") for _ in range(50)]

    history = build_point_history([cloud, *status_frames], max_frames=40)

    assert len(history) == 1
    assert history[0].is_current is False
