"""Community monitoring and classroom demo views for Streamlit."""

from __future__ import annotations

from datetime import datetime
from html import escape
import os

import pandas as pd
import streamlit as st

from ld6002c_fall.community import (
    CommunityController,
    CommunityRuntimeHealthStore,
    DemoAction,
    DemoControlResult,
    DemoControlService,
    Resident,
    ResidentState,
    latest_alarm_resident_id,
)
from ld6002c_fall.config import DEFAULT_COMMUNITY_RUNTIME_PATH


STATUS_LABELS = {
    "NORMAL": "正常监护",
    "WARNING": "疑似异常",
    "FALL": "跌倒报警",
    "OFFLINE": "设备离线",
    "RECOVERED": "已恢复",
}

EVENT_LABELS = {
    "FALL_ALERT": "跌倒报警",
    "ALERT_ACKNOWLEDGED": "报警已确认",
    "RECOVERED": "已恢复正常",
    "DEVICE_OFFLINE": "设备离线",
    "DEVICE_ONLINE": "设备上线",
    "DEMO_INJECTED": "演示数据注入",
}


def render_community_dashboard(controller: CommunityController) -> None:
    states = controller.states()
    events = controller.recent_events(80)
    _select_latest_alarm(controller, states)

    _render_statistics(controller, states, events)
    matrix_col, detail_col = st.columns([2.25, 1], gap="medium")
    with matrix_col:
        _render_resident_matrix(controller, states)
    with detail_col:
        with st.container(key="community-detail-panel"):
            _render_selected_resident(controller, states, events)
    _render_recent_events(events)


def render_demo_console(controller: CommunityController) -> None:
    st.markdown(
        '<div class="section-heading"><div><div class="section-kicker">Demo Control</div>'
        '<h2>社区演示数据控制台</h2></div>'
        '<span>演示覆盖会保持到“恢复正常”</span></div>',
        unsafe_allow_html=True,
    )
    _render_runtime_health()
    residents = controller.registry.residents
    labels = {
        resident.id: f"{resident.address}  {resident.name} · {resident.age}岁"
        for resident in residents
    }
    selected_id = st.selectbox(
        "住户选择",
        options=[resident.id for resident in residents],
        format_func=labels.__getitem__,
        key="demo_resident_id",
    )
    resident = controller.registry.get(selected_id)
    source_text = (
        f"真实绑定：{resident.sensor_binding} · 当前操作为演示覆盖"
        if resident.has_live_sensor
        else "数据来源：模拟社区监护点"
    )
    st.caption(source_text)

    actions: tuple[tuple[str, DemoAction, str], ...] = (
        ("发送正常数据", "NORMAL", ":material/check_circle:"),
        ("发送跌倒数据", "FALL", ":material/warning:"),
        ("发送疑似异常", "WARNING", ":material/error:"),
        ("模拟设备离线", "OFFLINE", ":material/link_off:"),
        ("恢复正常", "RECOVER", ":material/restart_alt:"),
        ("确认报警", "ACKNOWLEDGE", ":material/done_all:"),
    )
    for row in range(2):
        columns = st.columns(3, gap="small")
        for column, (label, action, icon) in zip(columns, actions[row * 3 : row * 3 + 3]):
            with column:
                if st.button(
                    label,
                    key=f"demo-action-{action}",
                    icon=icon,
                    use_container_width=True,
                ):
                    result = _execute_demo_action(controller, selected_id, action)
                    st.session_state["demo_last_result"] = result
                    st.rerun()

    _render_demo_result(st.session_state.get("demo_last_result"))
    states = controller.states()
    _render_demo_state(controller, states[selected_id])


def _render_statistics(
    controller: CommunityController,
    states: dict[str, ResidentState],
    events: list[dict[str, str]],
) -> None:
    today = datetime.now().astimezone().date()
    today_alerts = sum(
        1
        for event in events
        if event.get("event") == "FALL_ALERT"
        and _event_date(event.get("timestamp", "")) == today
    )
    statistics = (
        ("监护住户", len(controller.registry.residents)),
        ("在线设备", sum(state.status != "OFFLINE" for state in states.values())),
        ("正常住户", sum(state.status in {"NORMAL", "RECOVERED"} for state in states.values())),
        ("当前报警", sum(state.status == "FALL" for state in states.values())),
        ("今日报警", today_alerts),
    )
    cards = "".join(
        '<div class="community-stat"><span>'
        f'{escape(label)}</span><strong>{value}</strong></div>'
        for label, value in statistics
    )
    st.markdown(f'<div class="community-stats">{cards}</div>', unsafe_allow_html=True)


def _render_resident_matrix(
    controller: CommunityController,
    states: dict[str, ResidentState],
) -> None:
    st.markdown(
        '<div class="section-heading"><div><div class="section-kicker">Resident Matrix</div>'
        '<h2>住户安全状态</h2></div><span>18 个监护点 · 3 栋</span></div>',
        unsafe_allow_html=True,
    )
    residents = controller.registry.residents
    for start in range(0, len(residents), 5):
        columns = st.columns(5, gap="small")
        for column, resident in zip(columns, residents[start : start + 5]):
            state = states[resident.id]
            selected = st.session_state.get("selected_resident_id") == resident.id
            selected_class = "-selected" if selected else ""
            with column:
                with st.container(
                    key=f"resident-card-{state.status.lower()}{selected_class}-{resident.id}"
                ):
                    status_label = STATUS_LABELS[state.status]
                    handled = " · 已确认" if state.status == "FALL" and state.handled else ""
                    time_label = _short_time(state.alarm_time or state.updated_at)
                    label = (
                        f"{resident.address}\n"
                        f"{resident.name} · {resident.age}岁\n"
                        f"{status_label}{handled} · {time_label}"
                    )
                    if st.button(
                        label,
                        key=f"select-resident-{resident.id}",
                        use_container_width=True,
                    ):
                        st.session_state["selected_resident_id"] = resident.id


def _render_selected_resident(
    controller: CommunityController,
    states: dict[str, ResidentState],
    events: list[dict[str, str]],
) -> None:
    resident_id = st.session_state.get("selected_resident_id")
    try:
        resident = controller.registry.get(str(resident_id))
    except KeyError:
        resident = controller.registry.residents[0]
        st.session_state["selected_resident_id"] = resident.id
    state = states[resident.id]
    kicker = "Current Alert" if state.status == "FALL" else "Resident Detail"
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">'
        f'{escape(kicker)}</div><h2>{escape(resident.address)}</h2></div>'
        f'<span class="panel-note">{escape(resident.id)}<br>{escape(state.source)}</span></div>',
        unsafe_allow_html=True,
    )
    _render_resident_summary(resident, state)
    if not resident.has_live_sensor or state.demo_override:
        st.caption("数据来源：SIMULATED RADAR DATA · CLASSROOM DEMO")

    action_columns = st.columns(2, gap="small")
    with action_columns[0]:
        if state.status == "FALL" and not state.handled:
            if st.button(
                "确认报警",
                key="community-acknowledge",
                icon=":material/done_all:",
                use_container_width=True,
            ):
                _execute_demo_action(controller, resident.id, "ACKNOWLEDGE")
                st.rerun()
        elif st.button(
            "恢复正常",
            key="community-recover",
            icon=":material/restart_alt:",
            use_container_width=True,
        ):
            _execute_demo_action(controller, resident.id, "RECOVER")
            st.rerun()
    with action_columns[1]:
        if st.button(
            "查看技术详情",
            key="community-open-technical",
            icon=":material/radar:",
            use_container_width=True,
        ):
            st.query_params["view"] = "technical"
            st.query_params["resident"] = resident.id
            st.rerun()

    latest_event = next(
        (event for event in reversed(events) if event.get("resident_id") == resident.id),
        None,
    )
    if latest_event:
        st.caption(
            f"最近事件：{EVENT_LABELS.get(latest_event.get('event', ''), latest_event.get('event', ''))}"
        )


def _render_resident_summary(resident: Resident, state: ResidentState) -> None:
    css_class = "danger" if state.status == "FALL" else (
        "warning" if state.status in {"WARNING", "OFFLINE"} else ""
    )
    alarm_time = _short_time(state.alarm_time) if state.alarm_time else "--:--:--"
    radar = _result_label(state.radar_result)
    ai = _result_label(state.ai_result)
    rows = (
        ("姓名 / 年龄", f"{resident.name} · {resident.age}岁"),
        ("雷达判断", radar),
        ("AI 判断", ai),
        ("模型", _business_model(state.ai_model)),
        ("报警时间", alarm_time),
        ("处理状态", "已确认" if state.handled else "待处理"),
    )
    details = "".join(
        f'<div class="detail-row"><span>{escape(label)}</span>'
        f'<strong>{escape(value)}</strong></div>'
        for label, value in rows
    )
    st.markdown(
        '<div class="state-hero"><div class="state-label">CURRENT STATE</div>'
        f'<div class="state-value {css_class}">{escape(STATUS_LABELS[state.status])}</div></div>'
        f'<div class="detail-list">{details}</div>',
        unsafe_allow_html=True,
    )


def _render_recent_events(
    events: list[dict[str, str]],
    *,
    title: str = "最近社区事件",
) -> None:
    st.markdown(
        '<div class="section-heading compact"><div><div class="section-kicker">Event Feed</div>'
        f'<h2>{escape(title)}</h2></div><span>最近 12 条</span></div>',
        unsafe_allow_html=True,
    )
    relevant = [
        event
        for event in events
        if event.get("event") != "DEMO_INJECTED"
    ][-12:]
    if not relevant:
        st.info("暂无社区报警或设备事件。")
        return
    rows = []
    for event in reversed(relevant):
        handled = "已处理" if event.get("event") == "ALERT_ACKNOWLEDGED" else ""
        rows.append(
            {
                "时间": _short_time_value(event.get("timestamp", "")),
                "住户": f"{event.get('building', '')}{event.get('room', '')} {event.get('name', '')}",
                "事件": EVENT_LABELS.get(event.get("event", ""), event.get("event", "")),
                "状态": handled or STATUS_LABELS.get(event.get("status", ""), event.get("status", "")),
                "来源": event.get("source", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", height=150, hide_index=True)


def _select_latest_alarm(
    controller: CommunityController,
    states: dict[str, ResidentState],
) -> None:
    latest_id = latest_alarm_resident_id(states)
    if latest_id is not None:
        alarm = states[latest_id]
        alarm_key = f"{latest_id}:{(alarm.alarm_time or alarm.updated_at).isoformat()}"
        if st.session_state.get("community_last_auto_alarm_key") != alarm_key:
            st.session_state["selected_resident_id"] = latest_id
            st.session_state["community_last_auto_alarm_key"] = alarm_key
            return
    selected = st.session_state.get("selected_resident_id")
    if selected not in states:
        try:
            selected = controller.registry.bound_to("LD6002C").id
        except KeyError:
            selected = controller.registry.residents[0].id
        st.session_state["selected_resident_id"] = selected


def _execute_demo_action(
    controller: CommunityController,
    resident_id: str,
    action: DemoAction,
) -> DemoControlResult:
    return DemoControlService(controller).execute(resident_id, action)


def _render_demo_result(result: object) -> None:
    if not isinstance(result, DemoControlResult):
        return
    if result.ai_result is None:
        st.success(
            f"场景请求已写入：{result.action}，后台监测服务正在应用。"
        )
        return
    message = (
        f"{result.source} · {result.ai_result.label} · "
        f"{result.ai_result.model} · {result.ai_result.inference_ms:.1f} ms\n\n"
        f"{result.ai_result.message}"
    )
    if result.alarm_triggered:
        message += "\n\n电脑语音报警已在跌倒状态边沿触发一次。"
    if result.ai_result.success:
        st.success(message)
    else:
        st.warning(f"AI_FALLBACK · {message}")


def _render_demo_state(controller: CommunityController, state: ResidentState) -> None:
    resident = controller.registry.get(state.resident_id)
    st.markdown(
        '<div class="section-heading compact"><div><div class="section-kicker">Current State</div>'
        f'<h2>{escape(resident.address)} · {escape(resident.name)}</h2></div>'
        f'<span>{escape(state.source)} · {_short_time(state.updated_at)}</span></div>',
        unsafe_allow_html=True,
    )
    _render_resident_summary(resident, state)


def _render_runtime_health() -> None:
    health = CommunityRuntimeHealthStore(
        os.getenv("LD6002C_COMMUNITY_RUNTIME_PATH", str(DEFAULT_COMMUNITY_RUNTIME_PATH))
    ).read()
    st.markdown(
        '<div class="section-heading compact"><div><div class="section-kicker">System Health</div>'
        '<h2>后台服务状态</h2></div></div>',
        unsafe_allow_html=True,
    )
    columns = st.columns(5, gap="small")
    values = (
        ("Community Runtime", health.runtime),
        ("Ollama", health.ollama),
        ("Model", health.model),
        ("Telemetry", health.telemetry),
        ("Alarm", health.alarm),
    )
    for column, (label, value) in zip(columns, values, strict=True):
        column.metric(label, value)
    ai_time = _short_time_value(health.last_ai_success or "")
    st.caption(f"AI Mode: {health.ai_mode} · Last AI response: {ai_time}")
    if health.last_ai_error:
        st.warning(f"AI backend: {health.last_ai_error}")
    if health.last_runtime_error:
        st.error(f"Runtime: {health.last_runtime_error}")


def _result_label(value: int | None) -> str:
    if value is None:
        return "--"
    return "FALL · 1" if value else "NORMAL · 0"


def _business_model(value: str | None) -> str:
    if value in {None, "", "fallback", "disabled", "not-requested"}:
        return "本地安全规则"
    return value


def _short_time(value: datetime | None) -> str:
    return value.astimezone().strftime("%H:%M:%S") if value else "--:--:--"


def _short_time_value(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value or "--:--:--"
    return _short_time(parsed)


def _event_date(value: str):
    try:
        return datetime.fromisoformat(value).astimezone().date()
    except ValueError:
        return None
