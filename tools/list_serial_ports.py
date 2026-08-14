#!/usr/bin/env python3
"""List serial devices and stable Linux by-id paths."""

from __future__ import annotations

from pathlib import Path

from serial.tools import list_ports


def stable_paths_by_device() -> dict[str, list[str]]:
    """Map resolved device paths to their /dev/serial/by-id aliases."""

    by_id = Path("/dev/serial/by-id")
    aliases: dict[str, list[str]] = {}
    if not by_id.is_dir():
        return aliases

    for path in sorted(by_id.iterdir()):
        try:
            device = str(path.resolve(strict=True))
        except OSError:
            continue
        aliases.setdefault(device, []).append(str(path))
    return aliases


def format_id(value: int | None) -> str:
    return f"0x{value:04X}" if value is not None else "-"


def main() -> None:
    aliases = stable_paths_by_device()
    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print("未发现串口设备。")
        return

    for index, port in enumerate(ports, start=1):
        print(f"[{index}] device:       {port.device}")
        print(f"    description:  {port.description or '-'}")
        print(f"    manufacturer: {port.manufacturer or '-'}")
        print(f"    VID:          {format_id(port.vid)}")
        print(f"    PID:          {format_id(port.pid)}")
        print(f"    serial_number:{' ' if port.serial_number else ''}{port.serial_number or '-'}")
        stable = aliases.get(str(Path(port.device).resolve()), [])
        print(f"    stable_path:  {', '.join(stable) if stable else '-'}")


if __name__ == "__main__":
    main()
