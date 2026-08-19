from __future__ import annotations

from types import SimpleNamespace

from ld6002c_fall import serial_reader
from ld6002c_fall.main import build_parser
from ld6002c_fall.serial_reader import SerialRadarReader


class FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.flushed = False
        self.in_waiting = 0

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        self.flushed = True

    def read(self, size: int) -> bytes:
        return b""

    def close(self) -> None:
        return None


def test_serial_reader_sends_official_user_log_command(monkeypatch) -> None:
    fake = FakeSerial()
    monkeypatch.setattr(
        serial_reader,
        "serial",
        SimpleNamespace(Serial=lambda **kwargs: fake),
    )
    reader = SerialRadarReader("/dev/fake")

    reader.set_user_log(True)

    assert fake.writes == [
        bytes.fromhex("01 00 00 00 04 01 0e f5 01 00 00 00 fe")
    ]
    assert fake.flushed is True


def test_serial_cli_enables_point_cloud_by_default() -> None:
    parser = build_parser()

    default_args = parser.parse_args(["--mode", "serial", "--port", "/dev/fake"])
    disabled_args = parser.parse_args(
        ["--mode", "serial", "--port", "/dev/fake", "--disable-point-cloud"]
    )

    assert default_args.point_cloud_enabled is True
    assert disabled_args.point_cloud_enabled is False


def test_cli_uses_computer_audio_and_disables_legacy_websocket_by_default() -> None:
    parser = build_parser()

    default_args = parser.parse_args(["--mode", "mock"])
    legacy_args = parser.parse_args(
        ["--mode", "mock", "--disable-audio-alarm", "--enable-websocket"]
    )

    assert default_args.audio_alarm_enabled is True
    assert default_args.alarm_volume == 100
    assert default_args.disable_websocket is True
    assert legacy_args.audio_alarm_enabled is False
    assert legacy_args.disable_websocket is False
