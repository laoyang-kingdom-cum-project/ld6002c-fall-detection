"""Command line entry point for the LD6002C fall detection demo."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Sequence

from .alarm import ConsoleAlarm
from .config import (
    DEFAULT_ALARM_COOLDOWN,
    DEFAULT_BAUDRATE,
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_LOG_PATH,
    DEFAULT_SUSPECT_SECONDS,
)
from .fall_detector import FallDetector
from .logger import CSVFrameLogger
from .mock_reader import MockRadarReader
from .radar_model import RadarFrame
from .serial_reader import SerialRadarReader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HLK-LD6002C 老人跌倒检测系统")
    parser.add_argument("--mode", choices=["mock", "serial"], default="mock", help="运行模式")
    parser.add_argument("--port", help="串口名称，例如 /dev/ttyUSB0 或 COM3")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="串口波特率")
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="CSV 日志保存路径",
    )
    parser.add_argument(
        "--suspect-seconds",
        type=float,
        default=DEFAULT_SUSPECT_SECONDS,
        help="进入疑似跌倒所需的连续跌倒秒数",
    )
    parser.add_argument(
        "--confirm-seconds",
        type=float,
        default=DEFAULT_CONFIRM_SECONDS,
        help="进入确认跌倒所需的连续跌倒秒数",
    )
    parser.add_argument(
        "--alarm-cooldown",
        type=float,
        default=DEFAULT_ALARM_COOLDOWN,
        help="确认跌倒后的报警冷却秒数",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.mode == "serial" and not args.port:
        raise SystemExit("serial 模式必须提供 --port，例如 --port /dev/ttyUSB0")

    detector = FallDetector(
        suspect_seconds=args.suspect_seconds,
        confirm_seconds=args.confirm_seconds,
        alarm_cooldown=args.alarm_cooldown,
    )
    frame_logger = CSVFrameLogger(args.log_path)
    alarm = ConsoleAlarm()

    print("老人跌倒检测系统启动")
    print(f"当前模式：{args.mode}")

    try:
        if args.mode == "mock":
            _run_mock(detector, frame_logger, alarm)
        else:
            _run_serial(args.port, args.baudrate, detector, frame_logger, alarm)
    except KeyboardInterrupt:
        print("\n系统已停止")
    except RuntimeError as exc:
        raise SystemExit(f"运行失败：{exc}") from exc


def _run_mock(
    detector: FallDetector,
    frame_logger: CSVFrameLogger,
    alarm: ConsoleAlarm,
) -> None:
    reader = MockRadarReader()
    while True:
        frame = reader.read()
        _process_frame(frame, detector, frame_logger, alarm)
        time.sleep(1)


def _run_serial(
    port: str,
    baudrate: int,
    detector: FallDetector,
    frame_logger: CSVFrameLogger,
    alarm: ConsoleAlarm,
) -> None:
    with SerialRadarReader(port=port, baudrate=baudrate) as reader:
        while True:
            frame = reader.read()
            if frame is None:
                time.sleep(0.05)
                continue
            _process_frame(frame, detector, frame_logger, alarm)


def _process_frame(
    frame: RadarFrame,
    detector: FallDetector,
    frame_logger: CSVFrameLogger,
    alarm: ConsoleAlarm,
) -> None:
    result = detector.update(frame)
    frame_logger.log(frame, result.state)

    print(
        f"{frame.timestamp:%H:%M:%S} "
        f"有人={frame.human_present} "
        f"跌倒={frame.fall_detected} "
        f"运动={frame.motion_state} "
        f"系统状态={result.state}"
    )

    if result.should_alarm:
        alarm.emit(frame, result.state)


if __name__ == "__main__":
    main()
