"""Local Ollama bridge for the teaching fall-detection pipeline."""

from .models import FallAIRequest, FallAIResult, OllamaHealth
from .ollama_client import OllamaFallAI
from .scheduler import AIInferenceScheduler, AITrigger

__all__ = [
    "AIInferenceScheduler",
    "AITrigger",
    "FallAIRequest",
    "FallAIResult",
    "OllamaFallAI",
    "OllamaHealth",
]
