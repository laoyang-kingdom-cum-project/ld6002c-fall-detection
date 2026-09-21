"""Operator controls for requesting community classroom demo scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..ai import FallAIResult, OllamaFallAI
from ..alarm import AlarmOutput
from .controller import CommunityController
from .models import DemoScenario, ResidentState, local_now
from .telemetry import CommunityTelemetryStore


DemoAction = Literal["NORMAL", "FALL", "WARNING", "OFFLINE", "RECOVER", "ACKNOWLEDGE"]


@dataclass(frozen=True)
class DemoControlResult:
    action: DemoAction
    state: ResidentState
    ai_result: FallAIResult | None
    source: str
    alarm_triggered: bool = False


class DemoControlService:
    """Persist desired scenarios; the launcher-owned runtime applies them.

    Legacy constructor arguments remain accepted so existing integrations do
    not break, but Streamlit never performs AI inference, alarm output, or
    telemetry writes.
    """

    def __init__(
        self,
        controller: CommunityController,
        ai: OllamaFallAI | None = None,
        telemetry: CommunityTelemetryStore | None = None,
        alarm: AlarmOutput | None = None,
    ) -> None:
        self.controller = controller
        del ai, telemetry, alarm

    def execute(
        self,
        resident_id: str,
        action: DemoAction,
        *,
        timestamp: datetime | None = None,
    ) -> DemoControlResult:
        now = timestamp or local_now()
        if action == "ACKNOWLEDGE":
            state = self.controller.acknowledge_alarm(
                resident_id,
                timestamp=now,
                source="DEMO",
            )
            return DemoControlResult(action, state, None, "DEMO_REQUEST")

        scenario: DemoScenario = "NORMAL" if action == "RECOVER" else action
        state = self.controller.request_demo_scenario(
            resident_id,
            scenario,
            timestamp=now,
            demo_override=action != "RECOVER",
        )
        return DemoControlResult(action, state, None, "DEMO_REQUEST")
