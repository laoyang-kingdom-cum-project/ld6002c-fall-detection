"""Extensible parser placeholder for HLK-LD6002C serial frames."""

from __future__ import annotations

from .radar_model import RadarFrame


class LD6002CParser:
    """Incremental parser for LD6002C bytes.

    The first project version intentionally does not guess the real frame
    format. Once the hardware and protocol document are available, implement
    framing and validation here while keeping the rest of the application
    unchanged.
    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> RadarFrame | None:
        """Add raw serial bytes and return one complete frame if available.

        TODO: 设备到货后，根据《LD6002C 跌倒检测串口协议文档》补充：
        - 帧头识别
        - 帧长度解析
        - 命令字解析
        - 数据区字段解析
        - 校验和或 CRC 校验
        - 异常帧丢弃和重同步逻辑
        """

        if not data:
            return None

        self.buffer.extend(data)
        return None

    def parse_frame(self, frame: bytes) -> RadarFrame:
        """Convert one validated LD6002C frame into a RadarFrame."""

        raise NotImplementedError(
            "LD6002C real protocol parsing is pending hardware frames and documentation."
        )
