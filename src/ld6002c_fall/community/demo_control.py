"""Operator-triggered demo inputs that can pass through the real AI bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Literal

from ..ai import FallAIRequest, FallAIResult, OllamaFallAI
from ..ai.ollama_client import disabled_ai_result
from ..alarm import AlarmOutput
from ..device_protocol import DeviceState
from ..event_logger import EventName
from ..radar_model import RadarFrame
from .controller import CommunityController
from .models import ResidentState, local_now
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
    """Translate classroom controls into auditable community transitions."""

    def __init__(
        self,
        controller: CommunityController,
        ai: OllamaFallAI | None,
        telemetry: CommunityTelemetryStore | None = None,
        alarm: AlarmOutput | None = None,
    ) -> None:
        self.controller = controller
        self.ai = ai
        self.telemetry = telemetry
        self.alarm = alarm

    def execute(
        self,
        resident_id: str,
        action: DemoAction,
        *,
        timestamp: datetime | None = None,
    ) -> DemoControlResult:
        now = timestamp or local_now()
        previous = self.controller.states()[resident_id]

        if action == "RECOVER":
            state = self.controller.recover(resident_id, timestamp=now, source="DEMO")
            self._close_alarm(previous, now, resident_id, "Operator recovered resident")
            self._write_scenario(resident_id, "NORMAL", disabled_ai_result(0), now)
            return DemoControlResult(action, state, None, "DEMO")
        if action == "ACKNOWLEDGE":
            state = self.controller.acknowledge_alarm(
                resident_id,
                timestamp=now,
                source="DEMO",
            )
            self._close_alarm(
                previous,
                now,
                resident_id,
                "Operator acknowledged alarm",
                log_cancel=not previous.handled,
            )
            return DemoControlResult(action, state, None, "DEMO")
        if action == "WARNING":
            state = self.controller.inject_demo(
                resident_id,
                "WARNING",
                timestamp=now,
                radar_result=1,
                ai_result=0,
                ai_model="not-requested",
                ai_success=False,
                source="DEMO",
                details="Simulated suspected fall",
            )
            frame = self._write_scenario(
                resident_id,
                "WARNING",
                disabled_ai_result(1),
                now,
            )
            self._log_technical_event(
                resident_id,
                "FALL_SUSPECTED",
                now,
                "SUSPECTED_FALL",
                "Classroom warning scenario",
                frame.raw if frame is not None else "",
            )
            if previous.status == "FALL":
                self._close_alarm(previous, now, resident_id, "Fall warning replaced alarm")
            return DemoControlResult(action, state, None, "DEMO")
        if action == "OFFLINE":
            state = self.controller.inject_demo(
                resident_id,
                "OFFLINE",
                timestamp=now,
                source="DEMO",
                details="Simulated device offline",
            )
            frame = self.telemetry.write_offline(resident_id, timestamp=now) if self.telemetry else None
            self._log_technical_event(
                resident_id,
                "DEVICE_DISCONNECTED",
                now,
                "DISCONNECTED",
                "Classroom device-offline scenario",
                frame.raw if frame is not None else "",
            )
            if previous.status == "FALL":
                self._close_alarm(previous, now, resident_id, "Device went offline")
            return DemoControlResult(action, state, None, "DEMO")

        is_fall = int(action == "FALL")
        ai_result = (
            self.ai.predict(FallAIRequest(is_fall), force=True)
            if self.ai is not None
            else disabled_ai_result(is_fall)
        )
        source = "DEMO_AI" if ai_result.success else "AI_FALLBACK"
        self._log_ai_events(resident_id, now, is_fall, ai_result)
        state, entering_fall = self.controller.inject_demo_transition(
            resident_id,
            "FALL" if ai_result.result else "NORMAL",
            timestamp=now,
            radar_result=is_fall,
            ai_result=ai_result.result,
            ai_model=ai_result.model,
            ai_success=ai_result.success,
            source=source,
            details=ai_result.message,
        )
        scenario = "FALL" if state.status == "FALL" else "NORMAL"
        frame = self._write_scenario(resident_id, scenario, ai_result, now)
        if entering_fall:
            raw = frame.raw if frame is not None else ""
            self._log_technical_event(
                resident_id,
                "FALL_DETECTED",
                now,
                "CONFIRMED_FALL",
                "Community demo fall confirmed",
                raw,
            )
            self._log_technical_event(
                resident_id,
                "ALARM_TRIGGERED",
                now,
                "CONFIRMED_FALL",
                "Desktop audio alarm triggered once on fall transition",
                raw,
            )
            if self.alarm is not None and frame is not None:
                self.alarm.emit(frame, "确认跌倒")
        elif previous.status == "FALL" and state.status != "FALL":
            self._close_alarm(previous, now, resident_id, "Fall condition cleared")
        return DemoControlResult(action, state, ai_result, source, entering_fall)

    def _write_scenario(
        self,
        resident_id: str,
        status: Literal["NORMAL", "WARNING", "FALL"],
        ai_result: FallAIResult,
        timestamp: datetime,
    ) -> RadarFrame | None:
        if self.telemetry is None:
            return None
        return self.telemetry.write_scenario(
            resident_id,
            status,
            ai_result,
            timestamp=timestamp,
            frame_count=30,
        )

    def _log_ai_events(
        self,
        resident_id: str,
        timestamp: datetime,
        is_fall: int,
        result: FallAIResult,
    ) -> None:
        request = json.dumps(
            {"is_fall": is_fall, "trigger": "demo_control", "model": result.model},
            ensure_ascii=False,
        )
        self._log_technical_event(
            resident_id,
            "AI_REQUEST",
            timestamp,
            "CONFIRMED_FALL" if is_fall else "NORMAL",
            request,
        )
        details = json.dumps(
            {
                "result": result.result,
                "label": result.label,
                "message": result.message,
                "model": result.model,
                "inference_ms": round(result.inference_ms, 1),
                "trigger": "demo_control",
            },
            ensure_ascii=False,
        )
        if result.success:
            event = "AI_RESPONSE"
        else:
            self._log_technical_event(
                resident_id,
                "AI_ERROR",
                timestamp,
                "CONFIRMED_FALL" if is_fall else "NORMAL",
                json.dumps({"message": result.message}, ensure_ascii=False),
            )
            event = "AI_FALLBACK"
        self._log_technical_event(
            resident_id,
            event,
            timestamp,
            "CONFIRMED_FALL" if result.result else "NORMAL",
            details,
        )

    def _close_alarm(
        self,
        previous: ResidentState,
        timestamp: datetime,
        resident_id: str,
        details: str,
        *,
        log_cancel: bool = True,
    ) -> None:
        if self.alarm is not None:
            self.alarm.close()
        if previous.status == "FALL" and log_cancel:
            self._log_technical_event(
                resident_id,
                "ALARM_CANCELLED",
                timestamp,
                "CANCELLED",
                details,
            )

    def _log_technical_event(
        self,
        resident_id: str,
        event: EventName,
        timestamp: datetime,
        state: DeviceState,
        details: str,
        raw: str = "",
    ) -> None:
        if self.telemetry is not None:
            self.telemetry.log_event(
                resident_id,
                event,
                timestamp=timestamp,
                state=state,
                details=details,
                raw=raw,
            )
