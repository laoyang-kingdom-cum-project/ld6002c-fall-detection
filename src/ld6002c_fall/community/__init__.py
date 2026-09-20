"""Community-level resident aggregation for the LD6002C course project."""

from .controller import CommunityController, latest_alarm_resident_id
from .demo_control import DemoAction, DemoControlResult, DemoControlService
from .models import CommunityEvent, CommunityStatus, Resident, ResidentState
from .registry import CommunityRegistry
from .state_store import CommunityEventLogger, CommunityStateStore

__all__ = [
    "CommunityController",
    "CommunityEvent",
    "CommunityEventLogger",
    "CommunityRegistry",
    "CommunityStateStore",
    "CommunityStatus",
    "DemoAction",
    "DemoControlResult",
    "DemoControlService",
    "Resident",
    "ResidentState",
    "latest_alarm_resident_id",
]
