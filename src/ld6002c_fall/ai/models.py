"""Typed request and response models for the local AI bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AILabel = Literal["NORMAL", "FALL"]


@dataclass(frozen=True)
class FallAIRequest:
    """Minimal sensor input accepted by the course AI layer."""

    is_fall: int

    def __post_init__(self) -> None:
        if self.is_fall not in (0, 1):
            raise ValueError("is_fall must be 0 or 1")


@dataclass(frozen=True)
class FallAIResult:
    """Validated AI decision or an explicitly marked fallback result."""

    result: int
    label: AILabel
    message: str
    model: str
    inference_ms: float
    success: bool
    cached: bool = False


@dataclass(frozen=True)
class OllamaHealth:
    """Startup health-check result for Ollama and the selected model."""

    connected: bool
    model_available: bool
    message: str
