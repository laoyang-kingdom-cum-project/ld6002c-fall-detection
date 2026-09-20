#!/usr/bin/env python3
"""Detect likely LD6002C CP210x serial ports for launch automation."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

import serial
from serial import SerialException
from serial.tools import list_ports


SILICON_LABS_VID = 0x10C4


def candidate_score(port: Any) -> int:
    """Return a confidence score based only on USB-UART identity metadata."""

    text = " ".join(
        str(value or "")
        for value in (
            getattr(port, "description", None),
            getattr(port, "manufacturer", None),
            getattr(port, "product", None),
            getattr(port, "hwid", None),
        )
    ).casefold()
    score = 4 if getattr(port, "vid", None) == SILICON_LABS_VID else 0
    if "cp2104" in text:
        score += 4
    elif "cp210x" in text:
        score += 3
    if "silicon labs" in text or "silicon laboratories" in text:
        score += 2
    return score


def port_record(port: Any) -> dict[str, object]:
    """Convert pyserial's platform-specific port object into stable JSON."""

    score = candidate_score(port)
    return {
        "device": str(getattr(port, "device", "")),
        "description": str(getattr(port, "description", "") or ""),
        "manufacturer": str(getattr(port, "manufacturer", "") or ""),
        "vid": getattr(port, "vid", None),
        "pid": getattr(port, "pid", None),
        "serial_number": str(getattr(port, "serial_number", "") or ""),
        "hwid": str(getattr(port, "hwid", "") or ""),
        "candidate_score": score,
        "is_ld6002c_candidate": score >= 3,
    }


def scan_ports() -> list[dict[str, object]]:
    """Return all serial ports sorted by device name."""

    ports = sorted(list_ports.comports(), key=lambda item: str(item.device))
    return [port_record(port) for port in ports]


def probe_port(port: str, baudrate: int = 115200) -> tuple[bool, str]:
    """Open and immediately close a port to catch access/ownership failures."""

    try:
        connection = serial.Serial(port=port, baudrate=baudrate, timeout=0.25)
        connection.close()
    except (SerialException, OSError, ValueError) as exc:
        return False, str(exc)
    return True, "serial port opened successfully"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect an LD6002C CP210x port")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--json", action="store_true", help="print all ports as JSON")
    action.add_argument("--probe", metavar="PORT", help="test whether PORT can be opened")
    parser.add_argument("--baudrate", type=int, default=115200)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.probe:
        ok, message = probe_port(args.probe, args.baudrate)
        print(json.dumps({"ok": ok, "port": args.probe, "message": message}))
        return 0 if ok else 2

    records = scan_ports()
    if args.json:
        print(json.dumps(records, ensure_ascii=False))
        return 0

    if not records:
        print("No serial ports found.")
        return 0
    for index, record in enumerate(records, start=1):
        marker = "LD6002C candidate" if record["is_ld6002c_candidate"] else "serial"
        print(
            f"[{index}] {record['device']} - {record['description'] or '-'} "
            f"({marker})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
