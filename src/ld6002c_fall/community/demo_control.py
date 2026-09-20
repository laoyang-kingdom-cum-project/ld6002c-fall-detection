"""Operator-triggered demo inputs that can pass through the real AI bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..ai import FallAIRequest, FallAIResult, OllamaFallAI
from ..ai.ollama_client import disabled_ai_result
from .controller import CommunityController
from .models import ResidentState


DemoAction = Literal["NORMAL", "FALL", "WARNING", "OFFLINE", "RECOVER", "ACKNOWLEDGE"]


@dataclass(frozen=True)
class DemoControlResult:
    action: DemoAction
    state: ResidentState
    ai_result: FallAIResult | None
    source: str


class DemoControlService:
    """Translate classroom controls into auditable community transitions."""

    def __init__(
        self,
        controller: CommunityController,
        ai: OllamaFallAI | None,
    ) -> None:
        self.controller = controller
        self.ai = ai

    def execute(
        self,
        resident_id: str,
        action: DemoAction,
        *,
        timestamp: datetime | None = None,
    ) -> DemoControlResult:
        if action == "RECOVER":
            state = self.controller.recover(resident_id, timestamp=timestamp, source="DEMO")
            return DemoControlResult(action, state, None, "DEMO")
        if action == "ACKNOWLEDGE":
            state = self.controller.acknowledge_alarm(
                resident_id,
                timestamp=timestamp,
                source="DEMO",
            )
            return DemoControlResult(action, state, None, "DEMO")
        if action == "WARNING":
            state = self.controller.inject_demo(
                resident_id,
                "WARNING",
                timestamp=timestamp,
                source="DEMO",
                details="Simulated suspected fall",
            )
            return DemoControlResult(action, state, None, "DEMO")
        if action == "OFFLINE":
            state = self.controller.inject_demo(
                resident_id,
                "OFFLINE",
                timestamp=timestamp,
                source="DEMO",
                details="Simulated device offline",
            )
            return DemoControlResult(action, state, None, "DEMO")

        is_fall = int(action == "FALL")
        ai_result = (
            self.ai.predict(FallAIRequest(is_fall), force=True)
            if self.ai is not None
            else disabled_ai_result(is_fall)
        )
        source = "DEMO_AI" if ai_result.success else "AI_FALLBACK"
        state = self.controller.inject_demo(
            resident_id,
            "FALL" if ai_result.result else "NORMAL",
            timestamp=timestamp,
            radar_result=is_fall,
            ai_result=ai_result.result,
            ai_model=ai_result.model,
            ai_success=ai_result.success,
            source=source,
            details=ai_result.message,
        )
        return DemoControlResult(action, state, ai_result, source)
