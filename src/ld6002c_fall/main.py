"""Command line entry point for the LD6002C fall detection demo."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .alarm import ConsoleAlarm
from .config import (
    DEFAULT_ALARM_COOLDOWN,
    DEFAULT_BAUDRATE,
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_EVENT_LOG_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_REPLAY_CHUNK_SIZE,
    DEFAULT_REPLAY_INTERVAL,
    DEFAULT_SUSPECT_SECONDS,
    DEFAULT_WEBSOCKET_HOST,
    DEFAULT_WEBSOCKET_PORT,
)
from .device_server import DeviceWebSocketServer
from .event_logger import CSVEventLogger, EventName, SystemEvent
from .fall_detector import FallDetector
from .logger import CSVFrameLogger
from .mock_reader import MOCK_SCENARIOS, MockRadarReader
from .radar_model import RadarFrame
from .replay_reader import ReplayRadarReader
from .serial_reader import SerialRadarReader
from .system_controller import SystemController


@dataclass
class RuntimeServices:
    """Services shared by all radar input modes."""

    detector: FallDetector
    frame_logger: CSVFrameLogger
    event_logger: CSVEventLogger
    alarm: ConsoleAlarm
    controller: SystemController
    device_server: DeviceWebSocketServer | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HLK-LD6002C 老人跌倒检测系统")
    parser.add_argument(
        "--mode",
        choices=["mock", "serial", "replay"],
        default="mock",
        help="运行模式",
    )
    parser.add_argument(
        "--mock-scenario",
        choices=MOCK_SCENARIOS,
        default="empty",
        help="mock 模式场景：empty 不报警，normal 一直有人，fall-demo 自动跌倒，presence-demo 无人/有人切换",
    )
    parser.add_argument("--port", help="串口名称，例如 /dev/ttyUSB0 或 COM3")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="串口波特率")
    parser.add_argument("--input", type=Path, help="replay 模式的原始 .bin 文件")
    parser.add_argument(
        "--replay-chunk-size",
        type=int,
        default=DEFAULT_REPLAY_CHUNK_SIZE,
        help="replay 每次送入解析器的字节数",
    )
    parser.add_argument(
        "--replay-interval",
        type=float,
        default=DEFAULT_REPLAY_INTERVAL,
        help="replay 每个解析结果之间的等待秒数",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="CSV 日志保存路径",
    )
    parser.add_argument(
        "--event-log-path",
        type=Path,
        default=DEFAULT_EVENT_LOG_PATH,
        help="业务事件 CSV 日志保存路径",
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
    parser.add_argument(
        "--websocket-host",
        default=DEFAULT_WEBSOCKET_HOST,
        help="StickS3 WebSocket 监听地址",
    )
    parser.add_argument(
        "--websocket-port",
        type=int,
        default=DEFAULT_WEBSOCKET_PORT,
        help="StickS3 WebSocket 监听端口",
    )
    parser.add_argument(
        "--disable-websocket",
        action="store_true",
        help="禁用 StickS3 WebSocket 服务",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.mode == "serial" and not args.port:
        raise SystemExit("serial 模式必须提供 --port，例如 --port /dev/ttyUSB0")
    if args.mode == "replay" and args.input is None:
        raise SystemExit("replay 模式必须提供 --input，例如 --input data/raw/fall.bin")
    if args.replay_chunk_size <= 0:
        raise SystemExit("--replay-chunk-size 必须大于 0")
    if args.replay_interval < 0:
        raise SystemExit("--replay-interval 不能小于 0")
    if not 1 <= args.websocket_port <= 65535:
        raise SystemExit("--websocket-port 必须在 1 到 65535 之间")

    runtime = RuntimeServices(
        detector=FallDetector(
            suspect_seconds=args.suspect_seconds,
            confirm_seconds=args.confirm_seconds,
            alarm_cooldown=args.alarm_cooldown,
        ),
        frame_logger=CSVFrameLogger(args.log_path),
        event_logger=CSVEventLogger(args.event_log_path),
        alarm=ConsoleAlarm(),
        controller=SystemController(),
    )

    if not args.disable_websocket:
        runtime.device_server = _build_device_server(
            args.websocket_host,
            args.websocket_port,
            runtime,
        )

    print("老人跌倒检测系统启动")
    print(f"当前模式：{args.mode}")

    try:
        if runtime.device_server is not None:
            runtime.device_server.start()
            print(
                f"StickS3 WebSocket：ws://{args.websocket_host}:{args.websocket_port}"
            )
        if args.mode == "mock":
            _run_mock(runtime, args.mock_scenario)
        elif args.mode == "serial":
            _run_serial(args.port, args.baudrate, runtime)
        else:
            _run_replay(
                args.input,
                args.replay_chunk_size,
                args.replay_interval,
                runtime,
            )
    except KeyboardInterrupt:
        print("\n系统已停止")
    except RuntimeError as exc:
        raise SystemExit(f"运行失败：{exc}") from exc
    finally:
        if runtime.device_server is not None:
            runtime.device_server.stop()


def _build_device_server(
    host: str,
    port: int,
    runtime: RuntimeServices,
) -> DeviceWebSocketServer:
    server: DeviceWebSocketServer

    def log_connection(event_name: EventName, source: str) -> None:
        runtime.event_logger.log(
            SystemEvent(
                timestamp=datetime.now().astimezone(),
                event=event_name,
                state=runtime.controller.state,
                source=source,
            )
        )

    def on_alarm_cancelled(source: str) -> None:
        timestamp = datetime.now().astimezone()
        event = runtime.controller.cancel_alarm(timestamp, source)
        if event is None:
            print(f"忽略来自 {source} 的取消请求：当前没有确认跌倒报警")
            return
        runtime.event_logger.log(event)
        server.broadcast_state("CANCELLED", timestamp)
        print(f"报警已由 {source} 取消")

    server = DeviceWebSocketServer(
        host=host,
        port=port,
        on_alarm_cancelled=on_alarm_cancelled,
        on_connected=lambda source: log_connection("DEVICE_CONNECTED", source),
        on_disconnected=lambda source: log_connection("DEVICE_DISCONNECTED", source),
    )
    return server


def _run_mock(
    runtime: RuntimeServices,
    scenario: str,
) -> None:
    reader = MockRadarReader(scenario=scenario)
    while True:
        frame = reader.read()
        _process_frame(frame, runtime, source="mock")
        time.sleep(1)


def _run_serial(
    port: str,
    baudrate: int,
    runtime: RuntimeServices,
) -> None:
    with SerialRadarReader(port=port, baudrate=baudrate) as reader:
        while True:
            frame = reader.read()
            if frame is None:
                time.sleep(0.05)
                continue
            _process_frame(frame, runtime, source="serial")


def _run_replay(
    input_path: Path,
    chunk_size: int,
    interval: float,
    runtime: RuntimeServices,
) -> None:
    frame_count = 0
    with ReplayRadarReader(input_path, chunk_size=chunk_size) as reader:
        while not reader.finished:
            frame = reader.read()
            if frame is None:
                continue
            _process_frame(frame, runtime, source="replay")
            frame_count += 1
            if interval:
                time.sleep(interval)
    print(f"回放完成：解析 {frame_count} 个 RadarFrame")


def _process_frame(
    frame: RadarFrame,
    runtime: RuntimeServices,
    source: str,
) -> None:
    detection = runtime.detector.update(frame)
    result = runtime.controller.process(frame, detection, source)
    runtime.frame_logger.log(frame, detection.state, source)
    for event in result.events:
        runtime.event_logger.log(event)

    if runtime.device_server is not None:
        runtime.device_server.broadcast_state(result.state, frame.timestamp)

    print(
        f"{frame.timestamp:%H:%M:%S} "
        f"来源={source} "
        f"有人={frame.human_present} "
        f"跌倒={frame.fall_detected} "
        f"运动={frame.motion_state} "
        f"系统状态={detection.state} "
        f"设备状态={result.state}"
    )

    if result.should_alarm:
        runtime.alarm.emit(frame, detection.state)


if __name__ == "__main__":
    main()
