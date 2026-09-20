"""Atomic JSON state persistence and append-only community event logging."""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import CommunityEvent, ResidentState, local_now
from .registry import CommunityRegistry


class CommunityStateStore:
    """Persist all resident states with portable lock and atomic replace."""

    def __init__(self, path: str | Path, registry: CommunityRegistry) -> None:
        self.path = Path(path)
        self.registry = registry
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, ResidentState]:
        with _file_lock(self.path):
            states, changed = self._read_merged_unlocked()
            if changed:
                self._write_unlocked(states)
            return states

    def update(
        self,
        resident_id: str,
        updater: Callable[[ResidentState], ResidentState],
    ) -> tuple[ResidentState, ResidentState]:
        self.registry.get(resident_id)
        with _file_lock(self.path):
            states, _ = self._read_merged_unlocked()
            previous = states[resident_id]
            updated = updater(previous)
            if updated.resident_id != resident_id:
                raise ValueError("State updater changed resident_id")
            if updated == previous:
                return previous, previous
            states[resident_id] = updated
            self._write_unlocked(states)
            return previous, updated

    def reset_all(self) -> dict[str, ResidentState]:
        """Reset persisted community state without touching radar frame logs."""

        with _file_lock(self.path):
            states = {
                resident.id: ResidentState(resident_id=resident.id)
                for resident in self.registry.residents
            }
            self._write_unlocked(states)
            return states

    def _read_merged_unlocked(self) -> tuple[dict[str, ResidentState], bool]:
        persisted: dict[str, object] = {}
        changed = not self.path.exists()
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Failed to read community state {self.path}: {exc}") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("residents"), dict):
                raise RuntimeError(f"Invalid community state structure: {self.path}")
            persisted = payload["residents"]

        states: dict[str, ResidentState] = {}
        for resident in self.registry.residents:
            raw = persisted.get(resident.id)
            if isinstance(raw, dict):
                states[resident.id] = ResidentState.from_mapping(
                    raw,
                    resident_id=resident.id,
                )
            else:
                states[resident.id] = ResidentState(resident_id=resident.id)
                changed = True
        if set(persisted) != set(states):
            changed = True
        return states, changed

    def _write_unlocked(self, states: dict[str, ResidentState]) -> None:
        payload = {
            "version": 1,
            "community_name": self.registry.community_name,
            "updated_at": local_now().isoformat(timespec="milliseconds"),
            "residents": {
                resident.id: states[resident.id].to_mapping()
                for resident in self.registry.residents
            },
        }
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise RuntimeError(f"Failed to write community state {self.path}: {exc}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class CommunityEventLogger:
    """Append resident events to a small CSV audit log."""

    fieldnames = [
        "timestamp",
        "resident_id",
        "building",
        "room",
        "name",
        "event",
        "status",
        "source",
        "radar_result",
        "ai_result",
        "details",
    ]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: CommunityEvent) -> None:
        timestamp = (
            event.timestamp
            if event.timestamp.tzinfo is not None
            else event.timestamp.astimezone()
        )
        row = {
            "timestamp": timestamp.isoformat(timespec="milliseconds"),
            "resident_id": event.resident_id,
            "building": event.building,
            "room": event.room,
            "name": event.name,
            "event": event.event,
            "status": event.status,
            "source": event.source,
            "radar_result": "" if event.radar_result is None else event.radar_result,
            "ai_result": "" if event.ai_result is None else event.ai_result,
            "details": event.details,
        }
        try:
            with _file_lock(self.path):
                write_header = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)
        except OSError as exc:
            raise RuntimeError(f"Failed to write community event log {self.path}: {exc}") from exc

    def read_recent(self, limit: int = 20) -> list[dict[str, str]]:
        if limit <= 0 or not self.path.exists():
            return []
        try:
            with _file_lock(self.path):
                with self.path.open(newline="", encoding="utf-8") as file:
                    rows = list(csv.DictReader(file))
        except OSError as exc:
            raise RuntimeError(f"Failed to read community event log {self.path}: {exc}") from exc
        return rows[-limit:]

    def clear_demo_events(self) -> int:
        """Remove classroom-injected events while preserving real sensor history."""

        if not self.path.exists():
            return 0
        demo_sources = {"DEMO", "DEMO_AI", "AI_FALLBACK", "COMMUNITY_DEMO"}
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with _file_lock(self.path):
                with self.path.open(newline="", encoding="utf-8") as file:
                    rows = list(csv.DictReader(file))
                kept = [row for row in rows if row.get("source", "") not in demo_sources]
                with temporary.open("w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=self.fieldnames)
                    writer.writeheader()
                    writer.writerows(kept)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
                return len(rows) - len(kept)
        except OSError as exc:
            raise RuntimeError(f"Failed to reset community events {self.path}: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def _file_lock(target: Path, timeout: float = 3.0) -> Iterator[None]:
    """Use an exclusive lock file so dashboard and producer updates cannot overlap."""

    lock_path = target.with_suffix(f"{target.suffix}.lock")
    deadline = time.monotonic() + timeout
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 30
                if stale:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for state lock {lock_path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
