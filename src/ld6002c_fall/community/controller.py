"""Community state transitions built on top of the existing detector output."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import (
    CommunityEvent,
    CommunityEventName,
    CommunityStatus,
    Resident,
    ResidentState,
    local_now,
)
from .registry import CommunityRegistry
from .state_store import CommunityEventLogger, CommunityStateStore


class CommunityController:
    """Map technical detector states to residents without changing radar logic."""

    def __init__(
        self,
        registry: CommunityRegistry,
        state_store: CommunityStateStore,
        event_logger: CommunityEventLogger,
    ) -> None:
        self.registry = registry
        self.state_store = state_store
        self.event_logger = event_logger
        self.state_store.load()

    @classmethod
    def from_paths(
        cls,
        config_path: str | Path,
        state_path: str | Path,
        event_path: str | Path,
    ) -> "CommunityController":
        registry = CommunityRegistry.load(config_path)
        return cls(
            registry,
            CommunityStateStore(state_path, registry),
            CommunityEventLogger(event_path),
        )

    def states(self) -> dict[str, ResidentState]:
        return self.state_store.load()

    def recent_events(self, limit: int = 20) -> list[dict[str, str]]:
        return self.event_logger.read_recent(limit)

    def update_from_sensor(
        self,
        resident_id: str,
        radar_result: int,
        ai_result: int,
        device_state: str,
        timestamp: datetime,
        *,
        ai_model: str | None = None,
        ai_success: bool | None = None,
        source: str = "LD6002C",
    ) -> ResidentState:
        """Map one existing SystemController result onto its bound resident."""

        resident = self.registry.get(resident_id)
        status = _status_from_device_state(device_state)

        def apply(previous: ResidentState) -> ResidentState:
            if previous.demo_override:
                return previous
            entering_fall = status == "FALL" and previous.status != "FALL"
            return replace(
                previous,
                status=status,
                radar_result=radar_result,
                ai_result=ai_result,
                ai_model=ai_model,
                ai_success=ai_success,
                alarm_time=timestamp if entering_fall else (
                    previous.alarm_time if status == "FALL" else None
                ),
                handled=False if entering_fall else previous.handled,
                updated_at=timestamp,
                source=source,
                demo_override=False,
            )

        previous, updated = self.state_store.update(resident_id, apply)
        if updated is previous:
            return updated
        self._log_transition(resident, previous, updated, source)
        return updated

    def inject_demo(
        self,
        resident_id: str,
        status: CommunityStatus,
        *,
        timestamp: datetime | None = None,
        radar_result: int | None = None,
        ai_result: int | None = None,
        ai_model: str | None = None,
        ai_success: bool | None = None,
        source: str = "DEMO",
        details: str = "",
    ) -> ResidentState:
        """Apply a persistent demo override until the operator recovers it."""

        resident = self.registry.get(resident_id)
        now = timestamp or local_now()

        def apply(previous: ResidentState) -> ResidentState:
            entering_fall = status == "FALL" and previous.status != "FALL"
            return replace(
                previous,
                status=status,
                radar_result=radar_result,
                ai_result=ai_result,
                ai_model=ai_model,
                ai_success=ai_success,
                alarm_time=now if entering_fall else (
                    previous.alarm_time if status == "FALL" else None
                ),
                handled=False if entering_fall else previous.handled,
                updated_at=now,
                source=source,
                demo_override=True,
            )

        previous, updated = self.state_store.update(resident_id, apply)
        self._log(
            resident,
            updated,
            "DEMO_INJECTED",
            source,
            details or json.dumps({"status": status}, ensure_ascii=False),
        )
        self._log_transition(resident, previous, updated, source, details)
        return updated

    def acknowledge_alarm(
        self,
        resident_id: str,
        *,
        timestamp: datetime | None = None,
        source: str = "OPERATOR",
    ) -> ResidentState:
        resident = self.registry.get(resident_id)
        now = timestamp or local_now()

        def apply(previous: ResidentState) -> ResidentState:
            if previous.status != "FALL":
                return previous
            return replace(previous, handled=True, updated_at=now)

        previous, updated = self.state_store.update(resident_id, apply)
        if previous.status == "FALL" and not previous.handled:
            self._log(resident, updated, "ALERT_ACKNOWLEDGED", source)
        return updated

    def recover(
        self,
        resident_id: str,
        *,
        timestamp: datetime | None = None,
        source: str = "OPERATOR",
    ) -> ResidentState:
        resident = self.registry.get(resident_id)
        now = timestamp or local_now()

        def apply(previous: ResidentState) -> ResidentState:
            return replace(
                previous,
                status="NORMAL",
                radar_result=0,
                ai_result=0,
                alarm_time=None,
                handled=False,
                updated_at=now,
                source=source,
                demo_override=False,
            )

        previous, updated = self.state_store.update(resident_id, apply)
        self._log(resident, updated, "RECOVERED", source)
        if previous.status == "OFFLINE":
            self._log(resident, updated, "DEVICE_ONLINE", source)
        return updated

    def _log_transition(
        self,
        resident: Resident,
        previous: ResidentState,
        updated: ResidentState,
        source: str,
        details: str = "",
    ) -> None:
        if previous.status == updated.status:
            return
        if previous.status == "OFFLINE" and updated.status != "OFFLINE":
            self._log(resident, updated, "DEVICE_ONLINE", source, details)
        if updated.status == "OFFLINE":
            self._log(resident, updated, "DEVICE_OFFLINE", source, details)
        elif updated.status == "FALL":
            self._log(resident, updated, "FALL_ALERT", source, details)
        elif previous.status in {"FALL", "WARNING"} and updated.status == "NORMAL":
            self._log(resident, updated, "RECOVERED", source, details)

    def _log(
        self,
        resident: Resident,
        state: ResidentState,
        event: CommunityEventName,
        source: str,
        details: str = "",
    ) -> None:
        self.event_logger.log(
            CommunityEvent(
                timestamp=state.updated_at,
                resident_id=resident.id,
                building=resident.building,
                room=resident.room,
                name=resident.name,
                event=event,
                status=state.status,
                source=source,
                radar_result=state.radar_result,
                ai_result=state.ai_result,
                details=details,
            )
        )


def latest_alarm_resident_id(states: dict[str, ResidentState]) -> str | None:
    """Return the latest unhandled fall, then the latest handled fall."""

    alarms = [state for state in states.values() if state.status == "FALL"]
    if not alarms:
        return None
    alarms.sort(
        key=lambda state: (
            state.handled,
            -(state.alarm_time or state.updated_at).timestamp(),
        )
    )
    return alarms[0].resident_id


def _status_from_device_state(device_state: str) -> CommunityStatus:
    normalized = device_state.strip().upper()
    if normalized == "CONFIRMED_FALL":
        return "FALL"
    if normalized in {"OBSERVING", "SUSPECTED_FALL"}:
        return "WARNING"
    if normalized in {"DISCONNECTED", "ERROR"}:
        return "OFFLINE"
    return "NORMAL"
