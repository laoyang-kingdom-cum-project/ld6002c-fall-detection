"""Load and validate the static community resident registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Resident


@dataclass(frozen=True)
class CommunityRegistry:
    """Validated community name and ordered residents."""

    community_name: str
    residents: tuple[Resident, ...]

    def __post_init__(self) -> None:
        ids = [resident.id for resident in self.residents]
        if not self.community_name:
            raise ValueError("community_name must not be empty")
        if not self.residents:
            raise ValueError("At least one resident is required")
        if len(ids) != len(set(ids)):
            raise ValueError("Resident ids must be unique")
        bindings = [
            resident.sensor_binding
            for resident in self.residents
            if resident.sensor_binding
        ]
        if len(bindings) != len(set(bindings)):
            raise ValueError("sensor_binding values must be unique")

    @classmethod
    def load(cls, path: str | Path) -> "CommunityRegistry":
        config_path = Path(path)
        try:
            payload: Any = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to load community config {config_path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("residents"), list):
            raise ValueError("community.json must contain a residents array")
        residents = tuple(
            Resident.from_mapping(item)
            for item in payload["residents"]
            if isinstance(item, dict)
        )
        if len(residents) != len(payload["residents"]):
            raise ValueError("Every residents entry must be a JSON object")
        return cls(str(payload.get("community_name", "")).strip(), residents)

    def get(self, resident_id: str) -> Resident:
        for resident in self.residents:
            if resident.id == resident_id:
                return resident
        raise KeyError(f"Unknown resident: {resident_id}")

    def bound_to(self, sensor_binding: str) -> Resident:
        for resident in self.residents:
            if resident.sensor_binding == sensor_binding:
                return resident
        raise KeyError(f"No resident is bound to sensor {sensor_binding}")
