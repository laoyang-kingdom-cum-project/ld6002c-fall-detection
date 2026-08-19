"""Scheduling policy for periodic and edge-triggered AI inference."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Literal

from .models import FallAIResult


AITrigger = Literal["initial", "transition", "periodic", "cached"]


class AIInferenceScheduler:
    """Request AI on startup, signal transitions, and a fixed interval."""

    def __init__(self, periodic_interval: float = 3.0) -> None:
        if periodic_interval <= 0:
            raise ValueError("periodic_interval must be greater than 0")
        self.periodic_interval = periodic_interval
        self._last_input: int | None = None
        self._last_request_at: datetime | None = None
        self._last_result: FallAIResult | None = None

    def next_trigger(self, is_fall: int, timestamp: datetime) -> AITrigger | None:
        """Return why a real request is due, or ``None`` for cached reuse."""

        if is_fall not in (0, 1):
            raise ValueError("is_fall must be 0 or 1")

        if self._last_input is None:
            trigger: AITrigger = "initial"
        elif is_fall != self._last_input:
            trigger = "transition"
        elif self._last_request_at is None:
            trigger = "initial"
        elif (timestamp - self._last_request_at).total_seconds() >= self.periodic_interval:
            trigger = "periodic"
        else:
            self._last_input = is_fall
            return None

        self._last_input = is_fall
        self._last_request_at = timestamp
        return trigger

    def remember(
        self,
        result: FallAIResult,
        *,
        completed_at: datetime | None = None,
    ) -> None:
        """Store the latest completed result for intermediate radar frames."""

        self._last_result = result
        if completed_at is not None:
            self._last_request_at = completed_at

    def cached_result(self) -> FallAIResult:
        """Return the most recent result without issuing another request."""

        if self._last_result is None:
            raise RuntimeError("AI scheduler has no completed result")
        return replace(self._last_result, inference_ms=0.0, cached=True)
