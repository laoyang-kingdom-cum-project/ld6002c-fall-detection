"""Bounded, append-safe CSV snapshots for the live dashboard."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path


DEFAULT_MAX_BYTES = 2_000_000


class CSVSnapshotError(RuntimeError):
    """Raised when a stable CSV snapshot cannot be decoded."""


def read_csv_tail(
    path: str | Path,
    *,
    max_rows: int = 600,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[dict[str, str]]:
    """Read complete rows from a bounded snapshot at the end of a CSV file.

    The producer appends and closes one row at a time. Reading only up to the
    size observed before opening the file prevents a concurrent append from
    leaking a half-written row into the dashboard.
    """

    if max_rows <= 0:
        raise ValueError("max_rows must be greater than 0")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than 0")

    csv_path = Path(path)
    try:
        snapshot_size = csv_path.stat().st_size
        with csv_path.open("rb") as file:
            header_bytes = file.readline()
            header_end = file.tell()
            if not header_bytes or snapshot_size <= header_end:
                return []

            chunked = snapshot_size - header_end > max_bytes
            if chunked:
                start = max(header_end, snapshot_size - max_bytes)
                file.seek(start)
                body = file.read(snapshot_size - start)
                newline = body.find(b"\n")
                body = body[newline + 1 :] if newline >= 0 else b""
            else:
                file.seek(header_end)
                body = file.read(snapshot_size - header_end)
    except OSError as exc:
        raise CSVSnapshotError(f"Failed to read {csv_path}: {exc}") from exc

    if body and not body.endswith(b"\n"):
        final_newline = body.rfind(b"\n")
        body = body[: final_newline + 1] if final_newline >= 0 else b""
    if not body:
        return []

    try:
        header_text = header_bytes.decode("utf-8-sig")
        header = next(csv.reader(StringIO(header_text), strict=True), [])
        body_text = body.decode("utf-8")
    except (UnicodeError, csv.Error) as exc:
        raise CSVSnapshotError(f"Failed to decode {csv_path}: {exc}") from exc
    if not header:
        return []

    rows = _parse_rows(body_text, expected_columns=len(header), path=csv_path)
    return [dict(zip(header, row, strict=True)) for row in rows[-max_rows:]]


def _parse_rows(
    text: str,
    *,
    expected_columns: int,
    path: Path,
) -> list[list[str]]:
    """Recover from a tail chunk that starts inside a multiline CSV field."""

    candidate = text
    for _ in range(8):
        try:
            parsed = list(csv.reader(StringIO(candidate, newline=""), strict=True))
        except csv.Error:
            newline = candidate.find("\n")
            if newline < 0:
                break
            candidate = candidate[newline + 1 :]
            continue

        valid = [row for row in parsed if len(row) == expected_columns]
        if valid or not parsed:
            return valid
        newline = candidate.find("\n")
        if newline < 0:
            break
        candidate = candidate[newline + 1 :]
    raise CSVSnapshotError(f"Failed to parse a stable CSV tail from {path}")
