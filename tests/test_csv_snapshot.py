from __future__ import annotations

import csv

from ld6002c_fall.csv_snapshot import read_csv_tail


def test_read_csv_tail_returns_only_the_requested_recent_rows(tmp_path) -> None:
    path = tmp_path / "frames.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["index", "message"])
        writer.writeheader()
        for index in range(20):
            writer.writerow({"index": index, "message": f"row {index}"})

    rows = read_csv_tail(path, max_rows=3, max_bytes=80)

    assert [row["index"] for row in rows] == ["17", "18", "19"]


def test_read_csv_tail_ignores_a_concurrent_partial_row(tmp_path) -> None:
    path = tmp_path / "frames.csv"
    path.write_text(
        "index,message\n1,complete\n2,still being written",
        encoding="utf-8",
    )

    rows = read_csv_tail(path)

    assert rows == [{"index": "1", "message": "complete"}]


def test_read_csv_tail_preserves_multiline_fields(tmp_path) -> None:
    path = tmp_path / "events.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["index", "details"])
        writer.writeheader()
        writer.writerow({"index": 1, "details": "first line\nsecond line"})
        writer.writerow({"index": 2, "details": "last"})

    rows = read_csv_tail(path)

    assert rows[0]["details"] == "first line\nsecond line"
    assert rows[-1]["index"] == "2"
