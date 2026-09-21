"""Application defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOG_PATH = Path("data/fall_log.csv")
DEFAULT_EVENT_LOG_PATH = Path("data/events.csv")
DEFAULT_COMMUNITY_CONFIG_PATH = Path(
    os.getenv("LD6002C_COMMUNITY_CONFIG_PATH", "config/community.json")
)
DEFAULT_COMMUNITY_STATE_PATH = Path(
    os.getenv("LD6002C_COMMUNITY_STATE_PATH", "data/community_state.json")
)
DEFAULT_COMMUNITY_EVENT_PATH = Path(
    os.getenv("LD6002C_COMMUNITY_EVENT_PATH", "data/community_events.csv")
)
DEFAULT_COMMUNITY_TELEMETRY_DIR = Path(
    os.getenv("LD6002C_COMMUNITY_TELEMETRY_DIR", "data/community_telemetry")
)
DEFAULT_COMMUNITY_RUNTIME_PATH = Path(
    os.getenv("LD6002C_COMMUNITY_RUNTIME_PATH", "data/community_runtime.json")
)
DEFAULT_COMMUNITY_TELEMETRY_INTERVAL = float(
    os.getenv("COMMUNITY_TELEMETRY_INTERVAL", "0.5")
)
DEFAULT_COMMUNITY_TELEMETRY_MAX_FRAMES = int(
    os.getenv("COMMUNITY_TELEMETRY_MAX_FRAMES", "60")
)
DEFAULT_REAL_TELEMETRY_STALE_SECONDS = float(
    os.getenv("REAL_TELEMETRY_STALE_SECONDS", "5")
)
DEFAULT_COMMUNITY_RESIDENT_ID = os.getenv("LD6002C_RESIDENT_ID", "B2-302")
DEFAULT_BAUDRATE = 115200
DEFAULT_SUSPECT_SECONDS = 2.0
DEFAULT_CONFIRM_SECONDS = 5.0
DEFAULT_ALARM_COOLDOWN = 30.0
DEFAULT_ALARM_SOUND_PATH = Path(
    os.getenv("ALARM_SOUND_PATH", "studio_video_1778294323944.mp3")
)
DEFAULT_ALARM_VOLUME = int(os.getenv("ALARM_VOLUME", "100"))
DEFAULT_AUDIO_ALARM_ENABLED = os.getenv("AUDIO_ALARM_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEFAULT_WEBSOCKET_HOST = "0.0.0.0"
DEFAULT_WEBSOCKET_PORT = 8765
DEFAULT_REPLAY_CHUNK_SIZE = 64
DEFAULT_REPLAY_INTERVAL = 0.05
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:0.6b")
DEFAULT_OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "10"))
DEFAULT_AI_PERIODIC_INTERVAL = float(os.getenv("AI_PERIODIC_INTERVAL", "3.0"))
DEFAULT_AI_ENABLED = os.getenv("AI_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@dataclass(frozen=True)
class DetectorConfig:
    """Configuration for the Python secondary decision logic."""

    suspect_seconds: float = DEFAULT_SUSPECT_SECONDS
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS
    alarm_cooldown: float = DEFAULT_ALARM_COOLDOWN
