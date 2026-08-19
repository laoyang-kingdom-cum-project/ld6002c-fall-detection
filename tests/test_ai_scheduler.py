from __future__ import annotations

from datetime import datetime, timedelta

from ld6002c_fall.ai.models import FallAIResult
from ld6002c_fall.ai.scheduler import AIInferenceScheduler


BASE = datetime(2026, 8, 15, 12, 0, 0)


def test_scheduler_requests_initial_periodic_and_transition_inputs() -> None:
    scheduler = AIInferenceScheduler(periodic_interval=3.0)

    assert scheduler.next_trigger(0, BASE) == "initial"
    assert scheduler.next_trigger(0, BASE + timedelta(seconds=1)) is None
    assert scheduler.next_trigger(0, BASE + timedelta(seconds=3)) == "periodic"
    assert scheduler.next_trigger(1, BASE + timedelta(seconds=3.1)) == "transition"
    assert scheduler.next_trigger(0, BASE + timedelta(seconds=3.2)) == "transition"


def test_scheduler_reuses_last_result_between_requests() -> None:
    scheduler = AIInferenceScheduler(periodic_interval=3.0)
    result = FallAIResult(0, "NORMAL", "正常", "qwen3:0.6b", 123.0, True)
    scheduler.remember(result)

    cached = scheduler.cached_result()

    assert cached.cached is True
    assert cached.inference_ms == 0.0
    assert cached.result == 0


def test_periodic_interval_starts_after_a_slow_inference_completes() -> None:
    scheduler = AIInferenceScheduler(periodic_interval=3.0)
    result = FallAIResult(0, "NORMAL", "正常", "qwen3:0.6b", 4000.0, True)
    assert scheduler.next_trigger(0, BASE) == "initial"
    scheduler.remember(result, completed_at=BASE + timedelta(seconds=4))

    assert scheduler.next_trigger(0, BASE + timedelta(seconds=5)) is None
    assert scheduler.next_trigger(0, BASE + timedelta(seconds=7)) == "periodic"
