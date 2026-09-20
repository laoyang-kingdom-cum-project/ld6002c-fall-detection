"""Command line entry point for the LD6002C fall detection demo."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .ai import (
    AIInferenceScheduler,
    AITrigger,
    FallAIRequest,
    FallAIResult,
    OllamaFallAI,
)
from .ai.ollama_client import disabled_ai_result
from .alarm import AlarmOutput, ConsoleAlarm, DesktopAudioAlarm
from .config import (
    DEFAULT_AI_ENABLED,
    DEFAULT_AI_PERIODIC_INTERVAL,
    DEFAULT_ALARM_COOLDOWN,
    DEFAULT_ALARM_SOUND_PATH,
    DEFAULT_ALARM_VOLUME,
    DEFAULT_AUDIO_ALARM_ENABLED,
    DEFAULT_BAUDRATE,
    DEFAULT_CONFIRM_SECONDS,
    DEFAULT_COMMUNITY_CONFIG_PATH,
    DEFAULT_COMMUNITY_EVENT_PATH,
    DEFAULT_COMMUNITY_RESIDENT_ID,
    DEFAULT_COMMUNITY_STATE_PATH,
    DEFAULT_EVENT_LOG_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    DEFAULT_REPLAY_CHUNK_SIZE,
    DEFAULT_REPLAY_INTERVAL,
    DEFAULT_SUSPECT_SECONDS,
    DEFAULT_WEBSOCKET_HOST,
    DEFAULT_WEBSOCKET_PORT,
)
from .community import CommunityController
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
    alarm: AlarmOutput
    controller: SystemController
    ai: OllamaFallAI | None = None
    ai_scheduler: AIInferenceScheduler | None = None
    device_server: DeviceWebSocketServer | None = None
    community_controller: CommunityController | None = None
    community_resident_id: str = DEFAULT_COMMUNITY_RESIDENT_ID


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
    point_cloud_group = parser.add_mutually_exclusive_group()
    point_cloud_group.add_argument(
        "--enable-point-cloud",
        dest="point_cloud_enabled",
        action="store_true",
        help="serial 模式启动时发送 0x010E，开启真实 3D 点云上报（默认）",
    )
    point_cloud_group.add_argument(
        "--disable-point-cloud",
        dest="point_cloud_enabled",
        action="store_false",
        help="serial 模式不发送 0x010E 点云上报命令",
    )
    parser.set_defaults(point_cloud_enabled=True)
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
        "--community-config-path",
        type=Path,
        default=DEFAULT_COMMUNITY_CONFIG_PATH,
        help="社区住户配置 JSON 路径",
    )
    parser.add_argument(
        "--community-state-path",
        type=Path,
        default=DEFAULT_COMMUNITY_STATE_PATH,
        help="社区动态状态 JSON 路径",
    )
    parser.add_argument(
        "--community-event-path",
        type=Path,
        default=DEFAULT_COMMUNITY_EVENT_PATH,
        help="社区事件 CSV 路径",
    )
    parser.add_argument(
        "--community-resident-id",
        default=DEFAULT_COMMUNITY_RESIDENT_ID,
        help="真实 LD6002C 绑定的住户 ID",
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
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument(
        "--enable-audio-alarm",
        dest="audio_alarm_enabled",
        action="store_true",
        help="确认跌倒时在电脑播放本地报警音（默认）",
    )
    audio_group.add_argument(
        "--disable-audio-alarm",
        dest="audio_alarm_enabled",
        action="store_false",
        help="禁用电脑声音，仅保留控制台报警",
    )
    parser.set_defaults(audio_alarm_enabled=DEFAULT_AUDIO_ALARM_ENABLED)
    parser.add_argument(
        "--alarm-sound",
        type=Path,
        default=DEFAULT_ALARM_SOUND_PATH,
        help="电脑报警音频文件路径",
    )
    parser.add_argument(
        "--alarm-volume",
        type=int,
        default=DEFAULT_ALARM_VOLUME,
        help="电脑播放音量，范围 0-100",
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
    websocket_group = parser.add_mutually_exclusive_group()
    websocket_group.add_argument(
        "--enable-websocket",
        dest="disable_websocket",
        action="store_false",
        help="启用旧 StickS3 WebSocket 兼容服务",
    )
    websocket_group.add_argument(
        "--disable-websocket",
        dest="disable_websocket",
        action="store_true",
        help="禁用旧 StickS3 WebSocket 服务（默认）",
    )
    parser.set_defaults(disable_websocket=True)
    ai_group = parser.add_mutually_exclusive_group()
    ai_group.add_argument(
        "--enable-ai",
        dest="ai_enabled",
        action="store_true",
        help="启用本地 Ollama AI 判断层",
    )
    ai_group.add_argument(
        "--disable-ai",
        dest="ai_enabled",
        action="store_false",
        help="禁用 AI，直接使用雷达原始跌倒结果",
    )
    parser.set_defaults(ai_enabled=DEFAULT_AI_ENABLED)
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Ollama API 地址",
    )
    parser.add_argument(
        "--ollama-model",
        default=DEFAULT_OLLAMA_MODEL,
        help="本地 Ollama 模型名称",
    )
    parser.add_argument(
        "--ollama-timeout",
        type=float,
        default=DEFAULT_OLLAMA_TIMEOUT,
        help="Ollama 请求超时秒数",
    )
    parser.add_argument(
        "--ai-periodic-interval",
        type=float,
        default=DEFAULT_AI_PERIODIC_INTERVAL,
        help="输入不变时重新请求 AI 的周期秒数",
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
    if args.ollama_timeout <= 0:
        raise SystemExit("--ollama-timeout 必须大于 0")
    if args.ai_periodic_interval <= 0:
        raise SystemExit("--ai-periodic-interval 必须大于 0")
    if not 0 <= args.alarm_volume <= 100:
        raise SystemExit("--alarm-volume 必须在 0 到 100 之间")

    ai = (
        OllamaFallAI(
            base_url=args.ollama_base_url,
            model=args.ollama_model,
            timeout=args.ollama_timeout,
        )
        if args.ai_enabled
        else None
    )

    alarm: AlarmOutput = (
        DesktopAudioAlarm(args.alarm_sound, volume=args.alarm_volume)
        if args.audio_alarm_enabled
        else ConsoleAlarm()
    )
    try:
        community_controller = CommunityController.from_paths(
            args.community_config_path,
            args.community_state_path,
            args.community_event_path,
        )
        bound_resident = community_controller.registry.get(args.community_resident_id)
        if bound_resident.sensor_binding != "LD6002C":
            raise ValueError(
                f"住户 {bound_resident.id} 未绑定 LD6002C 传感器"
            )
    except (KeyError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"社区监护配置无效：{exc}") from exc

    runtime = RuntimeServices(
        detector=FallDetector(
            suspect_seconds=args.suspect_seconds,
            confirm_seconds=args.confirm_seconds,
            alarm_cooldown=args.alarm_cooldown,
        ),
        frame_logger=CSVFrameLogger(args.log_path),
        event_logger=CSVEventLogger(args.event_log_path),
        alarm=alarm,
        controller=SystemController(),
        ai=ai,
        ai_scheduler=(
            AIInferenceScheduler(args.ai_periodic_interval)
            if ai is not None
            else None
        ),
        community_controller=community_controller,
        community_resident_id=args.community_resident_id,
    )

    if not args.disable_websocket:
        runtime.device_server = _build_device_server(
            args.websocket_host,
            args.websocket_port,
            runtime,
        )

    print("老人跌倒检测系统启动")
    print(f"当前模式：{args.mode}")
    _print_alarm_startup_status(alarm)
    _print_ai_startup_status(ai, args.ollama_model, args.ai_periodic_interval)

    try:
        if runtime.device_server is not None:
            runtime.device_server.start()
            print(
                f"StickS3 WebSocket：ws://{args.websocket_host}:{args.websocket_port}"
            )
        if args.mode == "mock":
            _run_mock(runtime, args.mock_scenario)
        elif args.mode == "serial":
            _run_serial(
                args.port,
                args.baudrate,
                runtime,
                point_cloud_enabled=args.point_cloud_enabled,
            )
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
        runtime.alarm.close()


def _print_alarm_startup_status(alarm: AlarmOutput) -> None:
    if not isinstance(alarm, DesktopAudioAlarm):
        print("[Alarm] 电脑语音：已禁用（仅控制台）")
        return
    if alarm.ready:
        print(f"[Alarm] 电脑语音：{alarm.sound_path} (音量 {alarm.volume}%)")
        return
    if not alarm.sound_path.is_file():
        print(f"[Alarm] 音频文件不存在：{alarm.sound_path}")
    else:
        print("[Alarm] 未找到 ffplay，仅保留控制台报警")


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
    *,
    point_cloud_enabled: bool,
) -> None:
    with SerialRadarReader(port=port, baudrate=baudrate) as reader:
        if point_cloud_enabled:
            reader.set_user_log(True)
            print("[Radar] 已发送 0x010E，等待 LD6002C 真实 3D 点云")
        else:
            print("[Radar] 未开启 User log，Dashboard 点云区将保持 WAITING")
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
    radar_is_fall = int(frame.fall_detected)
    ai_trigger: AITrigger | str = "disabled"
    did_request = False
    if runtime.ai is not None and runtime.ai_scheduler is not None:
        requested_trigger = runtime.ai_scheduler.next_trigger(
            radar_is_fall,
            frame.timestamp,
        )
        if requested_trigger is None:
            ai_trigger = "cached"
            ai_result = runtime.ai_scheduler.cached_result()
        else:
            ai_trigger = requested_trigger
            did_request = True
            _log_ai_event(
                runtime,
                frame,
                source,
                "AI_REQUEST",
                {
                    "is_fall": radar_is_fall,
                    "trigger": requested_trigger,
                    "model": runtime.ai.model,
                },
            )
            ai_result = runtime.ai.predict(FallAIRequest(radar_is_fall), force=True)
            runtime.ai_scheduler.remember(
                ai_result,
                completed_at=datetime.now(tz=frame.timestamp.tzinfo),
            )
            if ai_result.success:
                _log_ai_event(
                    runtime,
                    frame,
                    source,
                    "AI_RESPONSE",
                    {
                        "result": ai_result.result,
                        "label": ai_result.label,
                        "message": ai_result.message,
                        "model": ai_result.model,
                        "inference_ms": round(ai_result.inference_ms, 1),
                        "trigger": requested_trigger,
                    },
                )
            else:
                _log_ai_event(
                    runtime,
                    frame,
                    source,
                    "AI_ERROR",
                    {
                        "message": ai_result.message,
                        "model": runtime.ai.model,
                        "trigger": requested_trigger,
                    },
                )
                _log_ai_event(
                    runtime,
                    frame,
                    source,
                    "AI_FALLBACK",
                    {
                        "result": ai_result.result,
                        "message": ai_result.message,
                        "trigger": requested_trigger,
                    },
                )
    else:
        ai_result = disabled_ai_result(radar_is_fall)

    final_frame = replace(frame, fall_detected=bool(ai_result.result))
    detection = runtime.detector.update(final_frame)
    result = runtime.controller.process(final_frame, detection, source)
    ai_work_state = _ai_work_state(ai_result, did_request)
    runtime.frame_logger.log(
        frame,
        detection.state,
        source,
        ai_result,
        device_state=result.state,
        ai_work_state=ai_work_state,
        ai_trigger=ai_trigger,
    )
    for event in result.events:
        runtime.event_logger.log(event)

    if runtime.community_controller is not None:
        try:
            runtime.community_controller.update_from_sensor(
                runtime.community_resident_id,
                radar_result=radar_is_fall,
                ai_result=ai_result.result,
                device_state=result.state,
                timestamp=frame.timestamp,
                ai_model=ai_result.model,
                ai_success=ai_result.success,
                source=f"LD6002C:{source}",
            )
        except (KeyError, RuntimeError, ValueError) as exc:
            print(f"[Community] 住户状态同步失败：{exc}")

    if runtime.device_server is not None:
        runtime.device_server.broadcast_state(result.state, frame.timestamp)

    print(
        f"{frame.timestamp:%H:%M:%S} "
        f"来源={source} "
        f"有人={frame.human_present} "
        f"雷达跌倒={radar_is_fall} "
        f"AI结果={ai_result.result} "
        f"AI状态={_ai_status(ai_result.success, ai_result.model)} "
        f"运动={frame.motion_state} "
        f"系统状态={detection.state} "
        f"设备状态={result.state}"
    )

    if result.should_alarm:
        runtime.alarm.emit(final_frame, detection.state)


def _log_ai_event(
    runtime: RuntimeServices,
    frame: RadarFrame,
    source: str,
    event: EventName,
    details: dict[str, object],
) -> None:
    runtime.event_logger.log(
        SystemEvent(
            timestamp=frame.timestamp,
            event=event,
            state=runtime.controller.state,
            source=source,
            details=json.dumps(details, ensure_ascii=False, separators=(",", ":")),
            raw=frame.raw,
        )
    )


def _print_ai_startup_status(
    ai: OllamaFallAI | None,
    model: str,
    periodic_interval: float,
) -> None:
    if ai is None:
        print("[AI] AI bridge disabled")
        print("[AI] Using radar result directly")
        return

    health = ai.health_check()
    if health.connected and health.model_available:
        print("[AI] Ollama: connected")
        print(f"[AI] Model: {model}")
        print("[AI] AI bridge enabled")
        print(f"[AI] Periodic inference: every {periodic_interval:g}s + transitions")
        return

    if health.connected:
        print("[AI] Ollama: connected")
        print(f"[AI] Model unavailable: {model}")
        print(f"[AI] Run: ollama pull {model}")
    else:
        print("[AI] Ollama unavailable")
    print(f"[AI] {health.message}")
    print("[AI] Falling back to radar result")


def _ai_status(success: bool, model: str) -> str:
    if success:
        return "AI_SUCCESS"
    if model == "disabled":
        return "AI_DISABLED"
    return "AI_FALLBACK"


def _ai_work_state(ai_result: FallAIResult, did_request: bool) -> str:
    if ai_result.model == "disabled":
        return "IDLE"
    if not ai_result.success:
        return "FALLBACK"
    if ai_result.result == 1:
        return "FALL_DETECTED"
    return "COMPLETED" if did_request else "MONITORING"


if __name__ == "__main__":
    main()
