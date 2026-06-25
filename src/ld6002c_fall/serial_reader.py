"""Serial radar reader for the real LD6002C device."""

from __future__ import annotations

from .ld6002c_parser import LD6002CParser
from .radar_model import RadarFrame

try:
    import serial
    from serial import SerialException
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    serial = None  # type: ignore[assignment]

    class SerialException(Exception):
        """Fallback exception used when pyserial is not installed."""


class SerialRadarReader:
    """Read bytes from a serial port and pass them to LD6002CParser."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        parser: LD6002CParser | None = None,
        timeout: float = 1.0,
    ) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: pip install pyserial")
        if not port:
            raise ValueError("port is required in serial mode")

        self.parser = parser or LD6002CParser()
        try:
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        except SerialException as exc:
            raise RuntimeError(f"Failed to open serial port {port}: {exc}") from exc

    def read(self) -> RadarFrame | None:
        """Read available serial bytes and return a parsed frame when possible."""

        try:
            waiting = self._serial.in_waiting
            data = self._serial.read(waiting or 1)
        except SerialException as exc:
            raise RuntimeError(f"Failed to read serial data: {exc}") from exc

        if not data:
            return None
        return self.parser.feed(data)

    def close(self) -> None:
        """Close the serial port."""

        self._serial.close()

    def __enter__(self) -> "SerialRadarReader":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
