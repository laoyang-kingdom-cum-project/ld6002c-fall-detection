"""Community monitoring and classroom demo views for Streamlit."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
import os

import altair as alt
import pandas as pd
import plotly.graph_objects as go
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

    fall_count = sum(state.status == "FALL" for state in states.values())
    if fall_count > 0:
        alert_text = f"【紧急警报】当前社区检测到 {fall_count} 处跌倒报警事件，请立即处置并调度网格员！"
        st.markdown(
            f'<div class="current-alert danger">'
            f'<span class="status-badge alarm">● 跌倒报警 ALARM ({fall_count})</span>&nbsp;&nbsp;'
            f'<span>{escape(alert_text)}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="current-alert safe">'
            '<span class="status-badge safe">✓ 监护全域正常</span>&nbsp;&nbsp;'
            '<span>社区全部 18 个微波雷达监护点位生命体征平稳，无跌倒报警。</span></div>',
            unsafe_allow_html=True,
        )

    _render_statistics(controller, states, events)
    matrix_col, detail_col = st.columns([2.25, 1], gap="medium")
    with matrix_col:
        _render_resident_matrix(controller, states)
        _render_operation_buttons(controller, states)
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
        ("监护住户", len(controller.registry.residents), "stat-purple"),
        ("在线设备", sum(state.status != "OFFLINE" for state in states.values()), "stat-cyan"),
        ("正常住户", sum(state.status in {"NORMAL", "RECOVERED"} for state in states.values()), "stat-green"),
        ("当前报警", sum(state.status == "FALL" for state in states.values()), "stat-red"),
        ("今日报警", today_alerts, "stat-red" if today_alerts > 0 else "stat-amber"),
    )
    cards = "".join(
        f'<div class="community-stat {css_class}"><span>'
        f'{escape(label)}</span><strong>{value}</strong></div>'
        for label, value, css_class in statistics
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

    # MD3 Segmented Control Pills for Filtering: 全部 | 正常 | 关注 | 离线
    filter_options = ["全部", "正常", "关注", "离线"]
    selected_filter = st.segmented_control(
        "住户状态筛选",
        options=filter_options,
        default="全部",
        label_visibility="collapsed",
        key="resident_filter_segment",
    ) or "全部"

    def _matches_filter(res: Resident) -> bool:
        st_val = states[res.id].status
        if selected_filter == "全部":
            return True
        if selected_filter == "正常":
            return st_val in {"NORMAL", "RECOVERED"}
        if selected_filter == "关注":
            return st_val in {"FALL", "WARNING"}
        if selected_filter == "离线":
            return st_val == "OFFLINE"
        return True

    filtered_residents = [r for r in residents if _matches_filter(r)]

    if not filtered_residents:
        st.info("当前筛选条件下无匹配住户。")
        return

    # Render resident cards in grid of 5
    for start in range(0, len(filtered_residents), 5):
        columns = st.columns(5, gap="small")
        for column, resident in zip(columns, filtered_residents[start : start + 5]):
            state = states[resident.id]
            selected = st.session_state.get("selected_resident_id") == resident.id
            selected_class = "-selected" if selected else ""
            signal_icon = "📶" if state.status != "OFFLINE" else "📵"
            with column:
                with st.container(
                    key=f"resident-card-{state.status.lower()}{selected_class}-{resident.id}"
                ):
                    status_label = STATUS_LABELS[state.status]
                    handled = " · 已确认" if state.status == "FALL" and state.handled else ""
                    time_label = _short_time(state.alarm_time or state.updated_at)
                    if selected:
                        indicator = "● SELECTED"
                    elif state.status in {"NORMAL", "RECOVERED"}:
                        indicator = "● 安全监护"
                    elif state.status == "FALL":
                        indicator = "● 跌倒告警"
                    elif state.status == "WARNING":
                        indicator = "▲ 疑似异常"
                    else:
                        indicator = "○ 设备离线"
                    label = (
                        f"{resident.address}  {signal_icon}\n"
                        f"{resident.name} · {resident.age}岁\n"
                        f"[{indicator}] {status_label}{handled} · {time_label}"
                    )
                    if st.button(
                        label,
                        key=f"select-resident-{resident.id}",
                        use_container_width=True,
                    ):
                        st.session_state["selected_resident_id"] = resident.id


def _render_operation_buttons(
    controller: CommunityController,
    states: dict[str, ResidentState],
) -> None:
    resident_id = st.session_state.get("selected_resident_id")
    try:
        resident = controller.registry.get(str(resident_id))
    except KeyError:
        resident = controller.registry.residents[0]
    state = states.get(resident.id)

    st.markdown('<div style="height: 0.8rem;"></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3, gap="small")
    with col1:
        with st.container(key="community-bottom-btn-1"):
            if st.button(
                "查看历史报告",
                key="btn-history-report",
                icon=":material/history_edu:",
                use_container_width=True,
            ):
                st.toast(
                    f"【历史健康档案】已调取住户 {resident.name} ({resident.address}) 近 30 天跌倒风险与活动节律报告。",
                    icon="📋",
                )
    with col2:
        with st.container(key="community-bottom-btn-2"):
            if st.button(
                "联系家属",
                key="btn-contact-family",
                icon=":material/phone_in_talk:",
                use_container_width=True,
            ):
                st.toast(
                    f"【紧急呼叫】正在一键拨打住户 {resident.name} 的紧急联系人家属电话...",
                    icon="📞",
                )
    with col3:
        with st.container(key="community-bottom-btn-3"):
            if st.button(
                "生成护理建议",
                key="btn-generate-advice",
                icon=":material/psychology:",
                use_container_width=True,
            ):
                current_status = state.status if state else "NORMAL"
                if current_status == "FALL":
                    advice = "高危跌倒事件：建议立即指派网格员上门，协助老人保持平躺并拨打 120 检查髋关节与头部。"
                elif current_status == "WARNING":
                    advice = "疑似姿态异常：建议通过室内可视对讲核实老人状态，关注防滑拖鞋与夜起照明。"
                else:
                    advice = "日常健康监护：该住户活动指标正常，建议维持每日晨间起居步态监测与室内通道无障碍防跌倒巡查。"
                st.toast(f"【AI 护理建议】{advice}", icon="💡")


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
        f'{escape(kicker)}</div><h2 style="font-size:1.35rem;font-weight:700;margin:0.2rem 0 0;">{escape(resident.address)}</h2></div>'
        f'<span class="panel-note" style="font-weight:600;">{escape(resident.id)}<br>{escape(state.source)}</span></div>',
        unsafe_allow_html=True,
    )

    # 1. MD3 Status Capsule Pill at top of details
    _render_resident_status_capsule(state)

    # 2. Grid-structured parameters
    _render_resident_summary(resident, state)

    # 3. Plotly area height trend chart
    _render_resident_height_chart(state)
    if not resident.has_live_sensor or state.demo_override:
        st.caption("数据来源：SIMULATED RADAR DATA · CLASSROOM DEMO")

    # Action buttons for current resident state
    action_columns = st.columns(2, gap="small")
    with action_columns[0]:
        if state.status == "FALL" and not state.handled:
            with st.container(key="community-ack-btn"):
                if st.button(
                    "确认报警",
                    key="community-acknowledge",
                    icon=":material/done_all:",
                    use_container_width=True,
                ):
                    _execute_demo_action(controller, resident.id, "ACKNOWLEDGE")
                    st.rerun()
        else:
            with st.container(key="community-rec-btn"):
                if st.button(
                    "恢复正常",
                    key="community-recover",
                    icon=":material/restart_alt:",
                    use_container_width=True,
                ):
                    _execute_demo_action(controller, resident.id, "RECOVER")
                    st.rerun()
    with action_columns[1]:
        with st.container(key="community-tech-btn"):
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


def _render_resident_status_capsule(state: ResidentState) -> None:
    if state.status == "FALL":
        badge_style = "background: #BA1A1A; color: #FFFFFF; box-shadow: 0 4px 12px rgba(186,26,26,0.35);"
        badge_text = "● 紧急跌倒报警中 · 立即调度"
    elif state.status == "WARNING":
        badge_style = "background: #FFDCC2; color: #311100; border: 1px solid #FFB74D;"
        badge_text = "▲ 疑似跌倒姿态 · 持续二次判定"
    elif state.status == "OFFLINE":
        badge_style = "background: #E9EFF6; color: #74777F;"
        badge_text = "✕ 雷达传感器离线"
    else:
        badge_style = "background: #C4EED0; color: #00210E;"
        badge_text = "● 正常监护中 · 生命体征平稳"

    st.markdown(
        f'<div style="margin: 0.2rem 0 0.85rem; text-align: center;">'
        f'<span style="display: inline-block; padding: 0.5rem 1.4rem; border-radius: 9999px; '
        f'font-size: 0.86rem; font-weight: 700; letter-spacing: 0.03em; {badge_style}">'
        f'{badge_text}</span></div>',
        unsafe_allow_html=True,
    )


def _render_resident_summary(resident: Resident, state: ResidentState) -> None:
    alarm_time = _short_time(state.alarm_time) if state.alarm_time else "--:--:--"
    radar = _result_label(state.radar_result)
    ai = _result_label(state.ai_result)
    rows = [
        ("老人姓名", resident.name),
        ("年龄", f"{resident.age} 岁"),
        ("雷达状态", radar),
        ("AI 智能研判", ai),
        ("推理模型", _business_model(state.ai_model)),
        ("报警时间", alarm_time),
        ("处理状态", "已确认" if state.handled else "待处理"),
        ("数据信道", state.source),
    ]

    items_html = "".join(
        f'<div style="background:#F8F9FE;border-radius:14px;padding:0.5rem 0.65rem;display:flex;flex-direction:column;gap:0.15rem;">'
        f'<span style="font-size:0.68rem;color:#74777F;font-weight:700;text-transform:uppercase;">{escape(label)}</span>'
        f'<strong style="font-size:0.84rem;color:#1A1C1E;font-weight:700;overflow-wrap:anywhere;">{escape(str(value))}</strong>'
        f'</div>'
        for label, value in rows
    )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:0.45rem;margin-bottom:0.75rem;">'
        f'{items_html}</div>',
        unsafe_allow_html=True,
    )


def _render_resident_height_chart(state: ResidentState) -> None:
    st.markdown(
        '<div style="margin-top: 0.5rem; margin-bottom: 0.25rem; display: flex; '
        'justify-content: space-between; align-items: center;">'
        '<span style="font-size: 0.72rem; font-weight: 700; color: #44474E; text-transform: uppercase;">'
        '雷达人体离地高度走势 (30s)</span>'
        '<span style="font-size: 0.68rem; color: #005FB0; font-weight: 700;">毫米波微动追踪</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    now = datetime.now()
    points = []
    for i in range(30):
        t = now - timedelta(seconds=29 - i)
        if state.status == "FALL":
            if i < 12:
                height = 1.48 + 0.04 * ((i % 3) - 1)
            elif i < 16:
                decay = (i - 12) / 4.0
                height = 1.48 * (1.0 - decay) + 0.30 * decay
            else:
                height = 0.30 + 0.03 * ((i % 3) - 1)
        elif state.status == "WARNING":
            if i < 15:
                height = 1.45 + 0.05 * ((i % 4) - 1.5)
            else:
                height = 0.85 + 0.08 * ((i % 3) - 1)
        elif state.status == "OFFLINE":
            height = 0.0
        else:
            height = 1.46 + 0.05 * ((i % 5) - 2)
        points.append({"time": t, "height": round(height, 3)})

    df = pd.DataFrame(points)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["time"],
            y=df["height"],
            mode="lines",
            line=dict(color="#005FB0", width=3.5, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(0, 95, 176, 0.12)",
            name="离地高度",
            hovertemplate="%{x|%H:%M:%S}<br>高度: %{y:.2f} m<extra></extra>",
        )
    )
    fig.add_hline(
        y=0.4,
        line_dash="dash",
        line_color="#BA1A1A",
        line_width=2,
        annotation_text="跌倒警戒线 (0.4m)",
        annotation_position="top left",
        annotation_font=dict(size=10, color="#BA1A1A", family="sans-serif"),
    )
    fig.update_layout(
        height=155,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(0, 0, 0, 0.06)",
            gridwidth=1,
            griddash="dot",
            tickformat="%H:%M:%S",
            tickfont=dict(size=10, color="#74777F"),
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(0, 0, 0, 0.06)",
            gridwidth=1,
            griddash="dot",
            range=[0.0, 2.0],
            tickfont=dict(size=10, color="#74777F"),
            zeroline=False,
        ),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


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
