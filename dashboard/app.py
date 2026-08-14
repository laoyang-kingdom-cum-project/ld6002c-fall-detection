"""Streamlit dashboard for the LD6002C fall detection demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "data" / "fall_log.csv"
EVENT_LOG_PATH = PROJECT_ROOT / "data" / "events.csv"


def main() -> None:
    st.set_page_config(page_title="LD6002C 跌倒检测", layout="wide")
    st.title("LD6002C 跌倒检测")

    if not LOG_PATH.exists():
        st.info("还没有日志文件，请先运行主程序生成 data/fall_log.csv。")
        return

    try:
        data = pd.read_csv(LOG_PATH)
    except Exception as exc:  # Streamlit should show a friendly message.
        st.error(f"读取日志失败：{exc}")
        return

    if data.empty:
        st.info("日志文件为空，请先运行主程序。")
        return

    latest = data.iloc[-1]
    state = str(latest.get("system_state", "未知"))
    human_present = _format_bool(latest.get("human_present"))
    fall_detected = _format_bool(latest.get("fall_detected"))
    motion_state = str(latest.get("motion_state", "未知"))
    source = _format_source(latest)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("系统状态", state)
    col2.metric("人体存在", human_present)
    col3.metric("跌倒状态", fall_detected)
    col4.metric("运动状态", motion_state)
    col5.metric("数据来源", source)

    if state == "确认跌倒":
        st.error("⚠️ 跌倒报警")
    elif state == "疑似跌倒":
        st.warning("疑似跌倒")

    frame_tab, event_tab = st.tabs(["雷达帧", "业务事件"])
    with frame_tab:
        st.subheader("最近 50 条雷达帧")
        st.dataframe(data.tail(50), width="stretch", hide_index=True)

    with event_tab:
        st.subheader("最近 50 条业务事件")
        _show_events()


def _format_bool(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if str(value).lower() in {"true", "1", "yes"}:
        return "是"
    if str(value).lower() in {"false", "0", "no"}:
        return "否"
    return str(value)


def _format_source(row: pd.Series) -> str:
    source = str(row.get("source", "")).strip()
    if source and source.lower() != "nan":
        return source

    raw = str(row.get("raw", ""))
    if raw.startswith("mock:"):
        return "mock"
    if raw.strip():
        return "serial_or_replay"
    return "unknown"


def _show_events() -> None:
    if not EVENT_LOG_PATH.exists():
        st.info("还没有业务事件。设备连接、疑似跌倒或报警后会写入此处。")
        return
    try:
        events = pd.read_csv(EVENT_LOG_PATH)
    except Exception as exc:  # Streamlit should show a friendly message.
        st.error(f"读取事件日志失败：{exc}")
        return
    if events.empty:
        st.info("业务事件日志为空。")
        return
    st.dataframe(events.tail(50), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
