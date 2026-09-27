"""Launcher-owned background runtime for continuous community demo telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import csv
import json
import os
from pathlib import Path
import threading
import time

from ..ai import FallAIRequest, FallAIResult, OllamaFallAI
from ..ai.ollama_client import disabled_ai_result
from ..alarm import AlarmOutput, PlaybackCompletionAlarm
from ..device_protocol import DeviceState
from ..event_logger import EventName
from ..mock_reader import MockRadarStatus, build_mock_radar_frame
from ..radar_model import RadarFrame
from ..voice_announcement import ConsoleVoiceAnnouncement, VoiceAnnouncementOutput
from .controller import CommunityController
from .models import (
    CommunityStatus,
    DemoResponseMode,
    DemoScenario,
    ResidentState,
    local_now,
)
from .telemetry import CommunityTelemetryStore


@dataclass(frozen=True)
class CommunityRuntimeHealth:
    runtime: str = "STARTING"
    heartbeat: str | None = None
    ollama: str = "CHECKING"
    model: str = "not-configured"
    ai_mode: str = "FALLBACK"
    last_ai_success: str | None = None
    last_ai_error: str | None = None
    telemetry: str = "STARTING"
    alarm: str = "READY"
    voice: str = "UNAVAILABLE"
    demo_response_mode: str = "DIRECT"
    last_runtime_error: str | None = None


@dataclass(frozen=True)
class SimulatedAITrace:
    """Presentation-only AI steps emitted after a DIRECT transition is applied."""

    scenario: DemoScenario
    radar_result: int
    result: int
    display_model: str

    def steps(self) -> tuple[tuple[EventName, int, str], ...]:
        outcome = "FALL · 1" if self.result else "NORMAL · 0"
        confirmation: tuple[EventName, str]
        if self.scenario == "FALL":
            confirmation = ("FALL_CONFIRMED", "跌倒报警")
        elif self.scenario == "WARNING":
            confirmation = ("WARNING_CONFIRMED", "疑似异常，继续观察")
        else:
            confirmation = ("NORMAL_CONFIRMED", "正常状态确认")
        fusion_message = (
            "多源结果一致，进入跌倒报警"
            if self.scenario == "FALL"
            else "多源演示结果完成融合"
        )
        return (
            ("RADAR_INPUT", 0, "毫米波数据接收"),
            ("FEATURE_EXTRACTED", 70, "人体姿态与运动特征提取"),
            ("AI_REQUEST_SIMULATED", 140, "本地智能分析（演示链路）"),
            (
                "AI_RESULT_SIMULATED",
                210,
                f"{self.display_model} 展示结果：{outcome}",
            ),
            ("FUSION_RESULT", 280, fusion_message),
            (confirmation[0], 350, confirmation[1]),
        )


class CommunityRuntimeHealthStore:
    """Read and atomically replace the runtime health document."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> CommunityRuntimeHealth:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
            return CommunityRuntimeHealth(runtime="STOPPED", telemetry="INACTIVE")
        if not isinstance(payload, dict):
            return CommunityRuntimeHealth(runtime="STOPPED", telemetry="INACTIVE")
        fields = CommunityRuntimeHealth.__dataclass_fields__
        return CommunityRuntimeHealth(
            **{key: payload[key] for key in fields if key in payload}
        )

    def write(self, health: CommunityRuntimeHealth) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(asdict(health), file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise RuntimeError(f"Failed to write runtime health {self.path}: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class CommunityDemoRuntime:
    """Generate 2 Hz rolling telemetry and own domain side effects."""

    def __init__(
        self,
        controller: CommunityController,
        telemetry: CommunityTelemetryStore,
        health_store: CommunityRuntimeHealthStore,
        *,
        ai: OllamaFallAI | None = None,
        alarm: AlarmOutput | None = None,
        voice_announcement: VoiceAnnouncementOutput | None = None,
        interval_seconds: float = 0.5,
        real_log_path: str | Path | None = None,
        real_stale_seconds: float = 5.0,
        health_check_seconds: float = 15.0,
        demo_response_mode: DemoResponseMode = "DIRECT",
        simulated_model: str = "qwen3:0.6b",
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        if real_stale_seconds <= 0 or health_check_seconds <= 0:
            raise ValueError("freshness intervals must be greater than 0")
        if demo_response_mode not in {"DIRECT", "AI"}:
            raise ValueError("demo_response_mode must be DIRECT or AI")
        self.controller = controller
        self.telemetry = telemetry
        self.health_store = health_store
        self.ai = ai
        self.alarm = alarm
        self.voice_announcement = voice_announcement or ConsoleVoiceAnnouncement()
        self.interval_seconds = interval_seconds
        self.real_log_path = Path(real_log_path) if real_log_path else None
        self.real_stale_seconds = real_stale_seconds
        self.health_check_seconds = health_check_seconds
        self.demo_response_mode = demo_response_mode
        self.simulated_model = simulated_model
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._health_thread: threading.Thread | None = None
        self._started_at = local_now()
        self._health = CommunityRuntimeHealth(
            model=ai.model if ai is not None else "disabled",
            ai_mode="AI" if ai is not None else "DISABLED",
            ollama="CHECKING" if ai is not None else "DISABLED",
            alarm=_alarm_status(alarm),
            voice=_voice_status(self.voice_announcement),
            demo_response_mode=demo_response_mode,
        )
        self._last_results: dict[str, FallAIResult] = {}
        self._active_scenarios: dict[str, DemoScenario] = {}
        self._alarm_residents: set[str] = set()
        self._fall_voice_tokens: dict[str, object] = {}
        self._fall_voice_lock = threading.Lock()
        self._event_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, ready_timeout: float = 5.0) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="community-demo-runtime",
            daemon=True,
        )
        self._thread.start()
        if not self._ready_event.wait(ready_timeout):
            raise RuntimeError("Community runtime did not become ready in time")
        if self._health.runtime == "ERROR":
            raise RuntimeError(self._health.last_runtime_error or "Community runtime failed")
        self._health_thread = threading.Thread(
            target=self._run_health_checks,
            name="community-demo-health",
            daemon=True,
        )
        self._health_thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._cancel_pending_fall_voice()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        health_thread = self._health_thread
        if health_thread is not None and health_thread.is_alive():
            health_thread.join(timeout)
        if self.alarm is not None:
            self.alarm.close()
        self.voice_announcement.close()
        self._health = replace(
            self._health,
            runtime="STOPPED",
            heartbeat=local_now().isoformat(timespec="milliseconds"),
            telemetry="INACTIVE",
        )
        self.health_store.write(self._health)

    def tick(self, timestamp: datetime | None = None) -> None:
        """Run one deterministic iteration; exposed for focused tests."""

        now = timestamp or local_now()
        states = self.controller.states()
        for resident in self.controller.registry.residents:
            state = states[resident.id]
            pending = state.applied_scenario_revision < state.scenario_revision
            if pending:
                state = self._apply_requested_scenario(state, now)
            elif state.source == "INITIAL":
                state = self.controller.update_from_sensor(
                    resident.id,
                    radar_result=0,
                    ai_result=0,
                    device_state="NORMAL",
                    timestamp=now,
                    ai_model="not-requested",
                    ai_success=False,
                    source="COMMUNITY_DEMO",
                )
            elif (
                resident.has_live_sensor
                and not state.demo_override
                and state.source.startswith("LD6002C")
                and not self._real_data_is_fresh(now)
            ):
                state, _ = self.controller.inject_demo_transition(
                    resident.id,
                    state.desired_scenario,
                    timestamp=now,
                    radar_result=int(state.desired_scenario in {"WARNING", "FALL"}),
                    ai_result=int(state.desired_scenario == "FALL"),
                    ai_model="not-requested",
                    ai_success=False,
                    source="COMMUNITY_DEMO",
                    details="Real telemetry is stale; classroom simulation is active",
                    demo_override=False,
                    applied_scenario_revision=state.scenario_revision,
                    applied_scenario=state.desired_scenario,
                )

            if state.status == "FALL" and state.handled and resident.id in self._alarm_residents:
                self._close_alarm(resident.id, now)

            scenario = state.desired_scenario if not state.demo_override else _scenario_for(state)
            previous_scenario = self._active_scenarios.get(resident.id)
            if scenario == "OFFLINE":
                if previous_scenario != "OFFLINE" or not self.telemetry.has_frames(resident.id):
                    frame = self.telemetry.write_offline(resident.id, timestamp=now)
                    self._log_event(
                        resident.id,
                        "DEVICE_DISCONNECTED",
                        now,
                        "DISCONNECTED",
                        "Classroom device-offline scenario",
                        frame.raw,
                    )
                self._active_scenarios[resident.id] = scenario
                continue

            result = self._last_results.get(resident.id, disabled_ai_result(int(scenario == "FALL")))
            elapsed = max(0.0, (now - self._started_at).total_seconds())
            frame = build_mock_radar_frame(
                scenario,
                elapsed,
                timestamp=now,
                resident_id=resident.id,
            )
            self.telemetry.append_frame(resident.id, frame, scenario, result)
            self._active_scenarios[resident.id] = scenario

        self._health = replace(
            self._health,
            runtime="RUNNING",
            heartbeat=now.isoformat(timespec="milliseconds"),
            telemetry="ACTIVE",
            last_runtime_error=None,
        )
        self.health_store.write(self._health)

    def refresh_ai_health(self) -> None:
        now = local_now().isoformat(timespec="milliseconds")
        if self.ai is None:
            self._health = replace(
                self._health,
                ollama="DISABLED",
                ai_mode="DISABLED",
                last_ai_error=None,
            )
        else:
            health = self.ai.health_check()
            online = health.connected and health.model_available
            self._health = replace(
                self._health,
                ollama="ONLINE" if online else "OFFLINE",
                ai_mode="AI" if online else "FALLBACK",
                last_ai_success=now if online else self._health.last_ai_success,
                last_ai_error=None if online else health.message,
            )
        self.health_store.write(self._health)

    def _run(self) -> None:
        first_tick = True
        try:
            while not self._stop_event.is_set():
                started = time.monotonic()
                try:
                    self.tick()
                except Exception as exc:
                    if first_tick:
                        raise
                    self._health = replace(
                        self._health,
                        runtime="DEGRADED",
                        heartbeat=local_now().isoformat(timespec="milliseconds"),
                        telemetry="ERROR",
                        last_runtime_error=str(exc),
                    )
                    self.health_store.write(self._health)
                if first_tick:
                    first_tick = False
                    self._ready_event.set()
                elapsed = time.monotonic() - started
                remaining = max(0.0, self.interval_seconds - elapsed)
                if self._stop_event.wait(remaining):
                    break
        except Exception as exc:
            self._health = replace(
                self._health,
                runtime="ERROR",
                heartbeat=local_now().isoformat(timespec="milliseconds"),
                telemetry="ERROR",
                last_runtime_error=str(exc),
            )
            try:
                self.health_store.write(self._health)
            finally:
                self._ready_event.set()

    def _run_health_checks(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.refresh_ai_health()
            except Exception as exc:
                self._health = replace(
                    self._health,
                    ollama="OFFLINE",
                    ai_mode="FALLBACK" if self.ai is not None else "DISABLED",
                    last_ai_error=str(exc),
                )
                try:
                    self.health_store.write(self._health)
                except RuntimeError:
                    pass
            if self._stop_event.wait(self.health_check_seconds):
                break

    def _apply_requested_scenario(
        self,
        requested: ResidentState,
        timestamp: datetime,
    ) -> ResidentState:
        scenario = requested.desired_scenario
        response_mode = requested.demo_response_mode or self.demo_response_mode
        self._health = replace(
            self._health,
            demo_response_mode=response_mode,
        )
        radar_result = int(scenario in {"WARNING", "FALL"})
        applied_status: CommunityStatus
        if scenario == "BEND":
            ai_result = 0
            result = FallAIResult(
                result=0,
                label="NORMAL",
                message=(
                    "弯腰为课堂模拟姿态，未调用真实雷达或 AI 判断链路。"
                ),
                model="not-requested",
                inference_ms=0.0,
                success=False,
            )
            self._last_results[requested.resident_id] = result
            applied_status = "NORMAL"
            source = "DEMO_DIRECT"
            ai_model = "not-requested"
            ai_success = False
        elif response_mode == "DIRECT":
            ai_result = int(scenario == "FALL")
            result = FallAIResult(
                result=ai_result,
                label="FALL" if ai_result else "NORMAL",
                message="管理员指定状态已即时应用；AI 分析流为教学演示。",
                model="demo-direct",
                inference_ms=0.0,
                success=False,
            )
            self._last_results[requested.resident_id] = result
            applied_status = scenario
            source = "DEMO_DIRECT"
            ai_model = "demo-direct"
            ai_success = False
        elif scenario in {"NORMAL", "FALL"}:
            result = (
                disabled_ai_result(radar_result)
                if self.ai is None
                else self.ai.predict(
                    FallAIRequest(radar_result),
                    force=True,
                )
            )
            self._last_results[requested.resident_id] = result
            if self.ai is not None:
                self._log_ai_events(requested.resident_id, timestamp, radar_result, result)
            applied_status = "FALL" if result.result else "NORMAL"
            source = (
                "DEMO_RULE"
                if self.ai is None
                else ("DEMO_AI" if result.success else "AI_FALLBACK")
            )
            ai_result = result.result
            ai_model = result.model
            ai_success = result.success
            if self.ai is not None:
                self._health = replace(
                    self._health,
                    ai_mode="AI" if result.success else "FALLBACK",
                    last_ai_success=(
                        timestamp.isoformat(timespec="milliseconds")
                        if result.success
                        else self._health.last_ai_success
                    ),
                    last_ai_error=None if result.success else result.message,
                )
        else:
            result = disabled_ai_result(radar_result)
            self._last_results[requested.resident_id] = result
            applied_status = scenario
            source = "DEMO"
            ai_result = 0
            ai_model = "not-requested"
            ai_success = False

        previous_status = requested.status
        transition_details = (
            json.dumps(
                {
                    "posture_event": "BEND",
                    "simulated": True,
                    "sensor_capability": "DEMO_ONLY",
                },
                ensure_ascii=False,
            )
            if scenario == "BEND"
            else result.message
        )
        state, entering_fall = self.controller.inject_demo_transition(
            requested.resident_id,
            applied_status,
            timestamp=timestamp,
            radar_result=radar_result,
            ai_result=ai_result,
            ai_model=ai_model,
            ai_success=ai_success,
            source=source,
            details=transition_details,
            demo_override=requested.demo_override,
            applied_scenario_revision=requested.scenario_revision,
            applied_scenario=scenario,
            posture_event="BEND" if scenario == "BEND" else "NONE",
        )
        event_source = source if scenario == "BEND" else (
            "DEMO_DIRECT" if response_mode == "DIRECT" else None
        )
        if scenario == "BEND":
            frame = self._transition_frame(requested.resident_id, "BEND", timestamp)
            self._log_event(
                requested.resident_id,
                "BEND_SIMULATED",
                timestamp,
                "NORMAL",
                json.dumps(
                    {
                        "posture_event": "BEND",
                        "simulated": True,
                        "sensor_capability": "DEMO_ONLY",
                    },
                    ensure_ascii=False,
                ),
                frame.raw,
                source="DEMO_DIRECT",
            )
        if entering_fall:
            frame = self._transition_frame(requested.resident_id, "FALL", timestamp)
            self._log_event(
                requested.resident_id,
                "FALL_DETECTED",
                timestamp,
                "CONFIRMED_FALL",
                "Community demo fall confirmed",
                frame.raw,
                source=event_source,
            )
            self._log_event(
                requested.resident_id,
                "ALARM_TRIGGERED",
                timestamp,
                "CONFIRMED_FALL",
                "Desktop audio alarm triggered once on fall transition",
                frame.raw,
                source=event_source,
            )
            self._alarm_residents.add(requested.resident_id)
            if self.alarm is not None:
                self.alarm.emit(frame, "确认跌倒")
        elif previous_status == "FALL" and state.status != "FALL":
            self._close_alarm(
                requested.resident_id,
                timestamp,
                source=event_source,
            )
        if requested.voice_announcement_requested:
            if scenario == "FALL" and entering_fall:
                self._schedule_fall_voice(
                    requested.resident_id,
                    source=source,
                )
            elif scenario != "FALL":
                self._announce_scenario(
                    requested.resident_id,
                    scenario,
                    timestamp,
                    source=source,
                )
        if response_mode == "DIRECT" and scenario not in {"OFFLINE", "BEND"}:
            self._log_simulated_ai_trace(
                requested.resident_id,
                timestamp,
                scenario,
                radar_result,
                ai_result,
            )
        return state

    def _announce_scenario(
        self,
        resident_id: str,
        scenario: DemoScenario,
        timestamp: datetime,
        *,
        source: str,
        trigger: str = "scenario_transition",
    ) -> None:
        text = {
            "BEND": "检测到弯腰姿态，请注意安全。",
            "WARNING": "检测到疑似异常姿态，请注意观察。",
            "OFFLINE": "监护设备已离线，请检查设备连接。",
            "NORMAL": "当前监护状态已恢复正常。",
            "FALL": "检测到跌倒，请立即处理。",
        }.get(scenario)
        if text is None:
            return
        try:
            success = self.voice_announcement.announce(text)
        except Exception as exc:
            success = False
            print(f"[Voice] 状态语音播报失败：{exc}")
        details = json.dumps(
            {
                "text": text,
                "scenario": scenario,
                "enabled": True,
                "success": success,
                "backend": self.voice_announcement.backend,
                "source": source,
                "trigger": trigger,
            },
            ensure_ascii=False,
        )
        self._log_event(
            resident_id,
            "VOICE_ANNOUNCEMENT",
            timestamp,
            (
                "DISCONNECTED"
                if scenario == "OFFLINE"
                else "CONFIRMED_FALL"
                if scenario == "FALL"
                else "NORMAL"
            ),
            details,
            source=source,
        )

    def _schedule_fall_voice(self, resident_id: str, *, source: str) -> None:
        token = object()
        with self._fall_voice_lock:
            self._fall_voice_tokens[resident_id] = token

        registered = False
        if isinstance(self.alarm, PlaybackCompletionAlarm):
            try:
                registered = self.alarm.run_after_playback(
                    lambda: self._announce_pending_fall_voice(
                        resident_id,
                        token,
                        source=source,
                        trigger="alarm_playback_finished",
                    )
                )
            except Exception as exc:
                print(f"[Voice] 等待跌倒报警音结束失败：{exc}")
        if not registered:
            self._announce_pending_fall_voice(
                resident_id,
                token,
                source=source,
                trigger="alarm_playback_unavailable",
            )

    def _announce_pending_fall_voice(
        self,
        resident_id: str,
        token: object,
        *,
        source: str,
        trigger: str,
    ) -> None:
        if self._stop_event.is_set():
            self._cancel_pending_fall_voice(resident_id, token)
            return
        state = self.controller.states().get(resident_id)
        should_announce = (
            state is not None
            and state.status == "FALL"
            and not state.handled
            and state.desired_scenario == "FALL"
        )
        with self._fall_voice_lock:
            if self._fall_voice_tokens.get(resident_id) is not token:
                return
            self._fall_voice_tokens.pop(resident_id, None)
        if not should_announce:
            return
        self._announce_scenario(
            resident_id,
            "FALL",
            local_now(),
            source=source,
            trigger=trigger,
        )

    def _cancel_pending_fall_voice(
        self,
        resident_id: str | None = None,
        token: object | None = None,
    ) -> None:
        with self._fall_voice_lock:
            if resident_id is None:
                self._fall_voice_tokens.clear()
                return
            if token is None or self._fall_voice_tokens.get(resident_id) is token:
                self._fall_voice_tokens.pop(resident_id, None)

    def _transition_frame(
        self,
        resident_id: str,
        scenario: MockRadarStatus,
        timestamp: datetime,
    ) -> RadarFrame:
        return build_mock_radar_frame(
            scenario,
            max(0.0, (timestamp - self._started_at).total_seconds()),
            timestamp=timestamp,
            resident_id=resident_id,
        )

    def _close_alarm(
        self,
        resident_id: str,
        timestamp: datetime,
        *,
        source: str | None = None,
    ) -> None:
        self._cancel_pending_fall_voice(resident_id)
        self._alarm_residents.discard(resident_id)
        if self.alarm is not None and not self._alarm_residents:
            self.alarm.close()
        self._log_event(
            resident_id,
            "ALARM_CANCELLED",
            timestamp,
            "CANCELLED",
            "Fall condition cleared",
            source=source,
        )

    def _log_simulated_ai_trace(
        self,
        resident_id: str,
        timestamp: datetime,
        scenario: DemoScenario,
        radar_result: int,
        result: int,
    ) -> None:
        trace = SimulatedAITrace(
            scenario=scenario,
            radar_result=radar_result,
            result=result,
            display_model=self.simulated_model,
        )
        state: DeviceState = {
            "NORMAL": "NORMAL",
            "WARNING": "SUSPECTED_FALL",
            "FALL": "CONFIRMED_FALL",
            "OFFLINE": "DISCONNECTED",
        }[scenario]
        for event, offset_ms, message in trace.steps():
            details = json.dumps(
                {
                    "source": "DEMO_DIRECT",
                    "ai_mode": "SIMULATED",
                    "ai_success": False,
                    "simulated": True,
                    "step": event,
                    "message": message,
                    "is_fall": radar_result,
                    "result": result,
                    "model": "demo-direct",
                    "display_model": self.simulated_model,
                    "visual_offset_ms": offset_ms,
                    "simulated_elapsed_ms": 350 if offset_ms == 350 else None,
                },
                ensure_ascii=False,
            )
            self._log_event(
                resident_id,
                event,
                timestamp + timedelta(milliseconds=offset_ms),
                state,
                details,
                source="DEMO_DIRECT",
            )

    def _log_ai_events(
        self,
        resident_id: str,
        timestamp: datetime,
        is_fall: int,
        result: FallAIResult,
    ) -> None:
        request = json.dumps(
            {"is_fall": is_fall, "trigger": "scenario_transition", "model": result.model},
            ensure_ascii=False,
        )
        state: DeviceState = "CONFIRMED_FALL" if is_fall else "NORMAL"
        self._log_event(resident_id, "AI_REQUEST", timestamp, state, request)
        details = json.dumps(
            {
                "result": result.result,
                "label": result.label,
                "message": result.message,
                "model": result.model,
                "inference_ms": round(result.inference_ms, 1),
                "trigger": "scenario_transition",
            },
            ensure_ascii=False,
        )
        if result.success:
            event: EventName = "AI_RESPONSE"
        else:
            self._log_event(
                resident_id,
                "AI_ERROR",
                timestamp,
                state,
                json.dumps({"message": result.message}, ensure_ascii=False),
            )
            event = "AI_FALLBACK"
        self._log_event(resident_id, event, timestamp, state, details)

    def _log_event(
        self,
        resident_id: str,
        event: EventName,
        timestamp: datetime,
        state: DeviceState,
        details: str,
        raw: str = "",
        *,
        source: str | None = None,
    ) -> None:
        with self._event_lock:
            self.telemetry.log_event(
                resident_id,
                event,
                timestamp=timestamp,
                state=state,
                details=details,
                raw=raw,
                source=source,
            )

    def _real_data_is_fresh(self, now: datetime) -> bool:
        if self.real_log_path is None or not self.real_log_path.is_file():
            return False
        try:
            with self.real_log_path.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            if not rows:
                return False
            timestamp = datetime.fromisoformat(str(rows[-1]["timestamp"]))
            if timestamp.tzinfo is None:
                timestamp = timestamp.astimezone()
            return abs((now - timestamp).total_seconds()) <= self.real_stale_seconds
        except (OSError, ValueError, IndexError):
            return False


def _scenario_for(state: ResidentState) -> DemoScenario:
    if state.posture_event == "BEND" and state.desired_scenario == "BEND":
        return "BEND"
    return state.status if state.status in {"NORMAL", "WARNING", "FALL", "OFFLINE"} else "NORMAL"


def _alarm_status(alarm: AlarmOutput | None) -> str:
    if alarm is None:
        return "DISABLED"
    ready = getattr(alarm, "ready", True)
    return "READY" if ready else "CONSOLE_ONLY"


def _voice_status(voice: VoiceAnnouncementOutput) -> str:
    if voice.ready:
        return "READY"
    return "CONSOLE" if voice.backend == "console" else "UNAVAILABLE"
