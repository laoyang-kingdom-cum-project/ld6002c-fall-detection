"""Community-level resident aggregation for the LD6002C course project."""

from .controller import CommunityController, latest_alarm_resident_id
from .demo_control import DemoAction, DemoControlResult, DemoControlService
from .models import CommunityEvent, CommunityStatus, DemoScenario, Resident, ResidentState
from .runtime import (
    CommunityDemoRuntime,
    CommunityRuntimeHealth,
    CommunityRuntimeHealthStore,
)
from .registry import CommunityRegistry
from .state_store import CommunityEventLogger, CommunityStateStore
from .telemetry import (
    SIMULATED_SOURCE,
    SIMULATED_SOURCE_LABEL,
    CommunityTelemetryStore,
)

__all__ = [
    "CommunityController",
    "CommunityEvent",
    "CommunityEventLogger",
    "CommunityRegistry",
    "CommunityStateStore",
    "CommunityTelemetryStore",
    "CommunityStatus",
    "CommunityDemoRuntime",
    "CommunityRuntimeHealth",
    "CommunityRuntimeHealthStore",
    "DemoAction",
    "DemoControlResult",
    "DemoControlService",
    "DemoScenario",
    "Resident",
    "ResidentState",
    "SIMULATED_SOURCE",
    "SIMULATED_SOURCE_LABEL",
    "latest_alarm_resident_id",
]
