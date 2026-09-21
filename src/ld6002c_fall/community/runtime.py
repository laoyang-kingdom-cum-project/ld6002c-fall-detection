"""Launcher-owned background runtime for continuous community demo telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import csv
import json
import os
from pathlib import Path
import threading
import time

from ..ai import FallAIRequest, FallAIResult, OllamaFallAI
from ..ai.ollama_client import disabled_ai_result
from ..alarm import AlarmOutput
from ..device_protocol import DeviceState
from ..event_logger import EventName
from ..mock_reader import MockRadarStatus, build_mock_radar_frame
from ..radar_model import RadarFrame
from .controller import CommunityController
from .models import DemoScenario, ResidentState, local_now
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
    last_runtime_error: str | None = None


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
        interval_seconds: float = 0.5,
        real_log_path: str | Path | None = None,
        real_stale_seconds: float = 5.0,
        health_check_seconds: float = 15.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than 0")
        if real_stale_seconds <= 0 or health_check_seconds <= 0:
            raise ValueError("freshness intervals must be greater than 0")
        self.controller = controller
        self.telemetry = telemetry
        self.health_store = health_store
        self.ai = ai
        self.alarm = alarm
        self.interval_seconds = interval_seconds
        self.real_log_path = Path(real_log_path) if real_log_path else None
        self.real_stale_seconds = real_stale_seconds
        self.health_check_seconds = health_check_seconds
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
        )
        self._last_results: dict[str, FallAIResult] = {}
        self._active_scenarios: dict[str, DemoScenario] = {}
        self._alarm_residents: set[str] = set()

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
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        health_thread = self._health_thread
        if health_thread is not None and health_thread.is_alive():
            health_thread.join(timeout)
        if self.alarm is not None:
            self.alarm.close()
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
        try:
            self.tick()
            self._ready_event.set()
            while not self._stop_event.is_set():
                started = time.monotonic()
                remaining = max(0.0, self.interval_seconds - (time.monotonic() - started))
                if self._stop_event.wait(remaining):
                    break
                try:
                    self.tick()
                except Exception as exc:
                    self._health = replace(
                        self._health,
                        runtime="DEGRADED",
                        heartbeat=local_now().isoformat(timespec="milliseconds"),
                        telemetry="ERROR",
                        last_runtime_error=str(exc),
                    )
                    self.health_store.write(self._health)
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
        radar_result = int(scenario in {"WARNING", "FALL"})
        if scenario in {"NORMAL", "FALL"}:
            result = disabled_ai_result(radar_result) if self.ai is None else self.ai.predict(
                FallAIRequest(radar_result),
                force=True,
            )
            self._last_results[requested.resident_id] = result
            if self.ai is not None:
                self._log_ai_events(requested.resident_id, timestamp, radar_result, result)
            applied_status: DemoScenario = "FALL" if result.result else "NORMAL"
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
        state, entering_fall = self.controller.inject_demo_transition(
            requested.resident_id,
            applied_status,
            timestamp=timestamp,
            radar_result=radar_result,
            ai_result=ai_result,
            ai_model=ai_model,
            ai_success=ai_success,
            source=source,
            details=result.message,
            demo_override=requested.demo_override,
            applied_scenario_revision=requested.scenario_revision,
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
            )
            self._log_event(
                requested.resident_id,
                "ALARM_TRIGGERED",
                timestamp,
                "CONFIRMED_FALL",
                "Desktop audio alarm triggered once on fall transition",
                frame.raw,
            )
            self._alarm_residents.add(requested.resident_id)
            if self.alarm is not None:
                self.alarm.emit(frame, "确认跌倒")
        elif previous_status == "FALL" and state.status != "FALL":
            self._close_alarm(requested.resident_id, timestamp)
        return state

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

    def _close_alarm(self, resident_id: str, timestamp: datetime) -> None:
        self._alarm_residents.discard(resident_id)
        if self.alarm is not None and not self._alarm_residents:
            self.alarm.close()
        self._log_event(
            resident_id,
            "ALARM_CANCELLED",
            timestamp,
            "CANCELLED",
            "Fall condition cleared",
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
    ) -> None:
        self.telemetry.log_event(
            resident_id,
            event,
            timestamp=timestamp,
            state=state,
            details=details,
            raw=raw,
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
    return state.status if state.status in {"NORMAL", "WARNING", "FALL", "OFFLINE"} else "NORMAL"


def _alarm_status(alarm: AlarmOutput | None) -> str:
    if alarm is None:
        return "DISABLED"
    ready = getattr(alarm, "ready", True)
    return "READY" if ready else "CONSOLE_ONLY"
