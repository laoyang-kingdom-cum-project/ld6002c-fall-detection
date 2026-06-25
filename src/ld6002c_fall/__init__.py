"""LD6002C fall detection teaching project."""

from .fall_detector import DetectionResult, FallDetector
from .radar_model import RadarFrame

__all__ = ["DetectionResult", "FallDetector", "RadarFrame"]

__version__ = "0.1.0"
