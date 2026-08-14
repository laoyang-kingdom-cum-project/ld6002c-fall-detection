#!/usr/bin/env python3
"""Capture LD6002C serial bytes without interpreting their contents."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import serial
from serial import SerialException


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集 LD6002C 原始串口数据")
    parser.add_argument("--port", required=True, help="串口或 /dev/serial/by-id 稳定路径")
    parser.add_argument("--baudrate", type=int, default=115200, help="串口波特率")
    parser.add_argument("--output", type=Path, required=True, help="输出 .bin 文件")
    parser.add_argument("--scenario", default="unspecified", help="测试场景名称")
    parser.add_argument("--duration", type=float, help="自动停止秒数；省略则按 Ctrl+C 停止")
    parser.add_argument("--read-size", type=int, default=256, help="每次最多读取的字节数")
    return parser


def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(f"无法写入 metadata {path}: {exc}") from exc


def capture(args: argparse.Namespace) -> dict[str, Any]:
    if args.read_size <= 0:
        raise ValueError("--read-size 必须大于 0")
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration 必须大于 0")

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = output.with_suffix(".json")
    started_at = datetime.now().astimezone()
    metadata: dict[str, Any] = {
        "port": args.port,
        "baudrate": args.baudrate,
        "started_at": started_at.isoformat(timespec="seconds"),
        "ended_at": None,
        "scenario": args.scenario,
        "byte_count": 0,
        "status": "running",
    }
    _write_metadata(metadata_path, metadata)

    started_monotonic = time.monotonic()
    try:
        with output.open("wb") as binary_file:
            with serial.Serial(args.port, args.baudrate, timeout=0.2) as device:
                print(f"正在采集 {args.port} -> {output}")
                print("按 Ctrl+C 可安全停止。")
                while args.duration is None or time.monotonic() - started_monotonic < args.duration:
                    waiting = device.in_waiting
                    data = device.read(min(waiting or 1, args.read_size))
                    if not data:
                        continue

                    binary_file.write(data)
                    binary_file.flush()
                    metadata["byte_count"] += len(data)
                    offset = metadata["byte_count"] - len(data)
                    print(f"{offset:08X}  {data.hex(' ')}")
        metadata["status"] = "completed"
    except KeyboardInterrupt:
        metadata["status"] = "interrupted"
        print("\n采集已由用户停止。")
    except (OSError, SerialException) as exc:
        metadata["status"] = "error"
        metadata["error"] = str(exc)
        raise RuntimeError(f"采集失败：{exc}") from exc
    finally:
        metadata["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_metadata(metadata_path, metadata)

    return metadata


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        metadata = capture(args)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"已保存 {metadata['byte_count']} bytes，状态：{metadata['status']}")


if __name__ == "__main__":
    main()
