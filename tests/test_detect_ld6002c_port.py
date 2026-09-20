from __future__ import annotations

from types import SimpleNamespace

from serial import SerialException

from tools import detect_ld6002c_port
from tools.detect_ld6002c_port import candidate_score, port_record, probe_port


def _port(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "device": "COM5",
        "description": "",
        "manufacturer": "",
        "product": "",
        "vid": None,
        "pid": None,
        "serial_number": None,
        "hwid": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_cp2104_metadata_is_an_ld6002c_candidate() -> None:
    port = _port(
        description="Silicon Labs CP210x USB to UART Bridge",
        manufacturer="Silicon Labs",
        vid=0x10C4,
        pid=0xEA60,
    )

    record = port_record(port)

    assert candidate_score(port) >= 3
    assert record["is_ld6002c_candidate"] is True
    assert record["device"] == "COM5"


def test_unrelated_serial_adapter_is_not_selected_automatically() -> None:
    port = _port(
        device="COM4",
        description="USB-SERIAL CH340",
        manufacturer="wch.cn",
        vid=0x1A86,
        pid=0x7523,
    )

    record = port_record(port)

    assert candidate_score(port) == 0
    assert record["is_ld6002c_candidate"] is False


def test_probe_reports_an_occupied_port_without_traceback(monkeypatch) -> None:
    def fail_to_open(**_: object) -> None:
        raise SerialException("Access is denied")

    monkeypatch.setattr(detect_ld6002c_port.serial, "Serial", fail_to_open)

    ok, message = probe_port("COM5")

    assert ok is False
    assert "Access is denied" in message
