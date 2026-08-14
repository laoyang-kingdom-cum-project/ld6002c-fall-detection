"""Offline playback of captured LD6002C serial bytes."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from .ld6002c_parser import LD6002CParser
from .radar_model import RadarFrame


class ReplayRadarReader:
    """Feed a binary capture to the parser in configurable byte chunks."""

    def __init__(
        self,
        input_path: str | Path,
        parser: LD6002CParser | None = None,
        chunk_size: int = 64,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")

        self.input_path = Path(input_path)
        self.parser = parser or LD6002CParser()
        self.chunk_size = chunk_size
        self._file: BinaryIO | None = None
        self._eof = False
        self._finished = False

    @property
    def finished(self) -> bool:
        """Return whether all file bytes and buffered parser frames are consumed."""

        return self._finished

    def open(self) -> None:
        """Open the capture for reading and reset replay state."""

        if self._file is not None:
            return
        try:
            self._file = self.input_path.open("rb")
        except OSError as exc:
            raise RuntimeError(f"Failed to open replay file {self.input_path}: {exc}") from exc
        self.parser.reset()
        self._eof = False
        self._finished = False

    def read(self) -> RadarFrame | None:
        """Return the next normalized frame, or ``None`` at end of capture."""

        if self._file is None:
            self.open()

        buffered_frame = self.parser.feed(b"")
        if buffered_frame is not None:
            return buffered_frame

        assert self._file is not None
        while not self._eof:
            try:
                data = self._file.read(self.chunk_size)
            except OSError as exc:
                raise RuntimeError(f"Failed to read replay file {self.input_path}: {exc}") from exc

            if not data:
                self._eof = True
                break

            frame = self.parser.feed(data)
            if frame is not None:
                return frame

        self._finished = True
        return None

    def close(self) -> None:
        """Close the capture file."""

        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "ReplayRadarReader":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
