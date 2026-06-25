"""Streamlit dashboard for the LD6002C fall detection demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "data" / "fall_log.csv"


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

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("系统状态", state)
    col2.metric("人体存在", human_present)
    col3.metric("跌倒状态", fall_detected)
    col4.metric("运动状态", motion_state)

    if state == "确认跌倒":
        st.error("⚠️ 跌倒报警")
    elif state == "疑似跌倒":
        st.warning("疑似跌倒")

    st.subheader("最近 50 条日志")
    st.dataframe(data.tail(50), use_container_width=True, hide_index=True)


def _format_bool(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if str(value).lower() in {"true", "1", "yes"}:
        return "是"
    if str(value).lower() in {"false", "0", "no"}:
        return "否"
    return str(value)


if __name__ == "__main__":
    main()
