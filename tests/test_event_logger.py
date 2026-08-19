from __future__ import annotations

import csv
from datetime import datetime

from ld6002c_fall.event_logger import CSVEventLogger, SystemEvent


def test_event_logger_writes_raw_data(tmp_path) -> None:
    log_path = tmp_path / "events.csv"
    logger = CSVEventLogger(log_path)

    logger.log(
        SystemEvent(
            timestamp=datetime(2026, 8, 15, 12, 0, 0),
            event="FALL_DETECTED",
            state="CONFIRMED_FALL",
            source="serial",
            raw="55 01 00 01 0e 02 00",
        )
    )

    with log_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["raw"] == "55 01 00 01 0e 02 00"


def test_event_logger_migrates_legacy_log(tmp_path) -> None:
    log_path = tmp_path / "events.csv"
    log_path.write_text(
        "timestamp,event,state,source,details\n"
        "2026-08-15T12:00:00,FALL_SUSPECTED,SUSPECTED_FALL,serial,old row\n",
        encoding="utf-8",
    )

    CSVEventLogger(log_path)

    with log_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["details"] == "old row"
    assert rows[0]["raw"] == ""
