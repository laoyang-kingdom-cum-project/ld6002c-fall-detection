"""Community monitoring and classroom demo views for Streamlit."""

from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
import os
from typing import Mapping

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
    DemoResponseMode,
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
    "BEND_SIMULATED": "弯腰姿态",
}


def render_community_dashboard(
    controller: CommunityController,
    theme: Mapping[str, str],
) -> None:
    states = controller.states()
    events = controller.recent_events(80)
    _select_latest_alarm(controller, states)

    fall_count = sum(state.status == "FALL" for state in states.values())
    bend_count = sum(state.posture_event == "BEND" for state in states.values())
    if fall_count > 0:
        alert_text = f"【紧急警报】当前社区检测到 {fall_count} 处跌倒报警事件，请立即处置并调度网格员！"
        st.markdown(
            f'<div class="current-alert danger">'
            f'<span class="status-badge alarm">● 跌倒报警 ALARM ({fall_count})</span>&nbsp;&nbsp;'
            f'<span>{escape(alert_text)}</span></div>',
            unsafe_allow_html=True,
        )
    elif bend_count > 0:
        st.markdown(
            '<div class="current-alert posture">'
            f'<span class="status-badge posture">● 姿态关注 ({bend_count})</span>&nbsp;&nbsp;'
            '<span>检测到弯腰姿态，当前安全状态正常。</span></div>',
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
        with st.container(key="community-resident-area"):
            _render_resident_matrix(controller, states)
            _render_operation_buttons(controller, states)
    with detail_col:
        with st.container(key="community-detail-panel"):
            _render_selected_resident(controller, states, events, theme)
    with st.container(key="community-event-area"):
        _render_recent_events(events)


def render_demo_console(
    controller: CommunityController,
    _theme: Mapping[str, str],
) -> None:
    with st.container(key="demo-runtime-health"):
        _render_runtime_health()

    with st.container(key="demo-scenario-controls"):
        st.markdown(
            '<div class="demo-control-section-title"><div>'
            '<span>演示设置</span><strong>响应方式与目标住户</strong></div>'
            '<small>演示覆盖会保持到“恢复正常”</small></div>',
            unsafe_allow_html=True,
        )
        default_mode = os.getenv("LD6002C_DEMO_RESPONSE_MODE", "DIRECT").upper()
        if default_mode not in {"DIRECT", "AI"}:
            default_mode = "DIRECT"
        with st.container(key="demo-configuration"):
            mode_column, voice_column = st.columns([1.55, 1], gap="medium")
            with mode_column:
                response_mode = st.segmented_control(
                    "演示响应模式",
                    options=["DIRECT", "AI"],
                    default=default_mode,
                    format_func=lambda value: (
                        "即时演示" if value == "DIRECT" else "AI完整链路"
                    ),
                    selection_mode="single",
                    key="demo_response_mode",
                )
            with voice_column:
                voice_announcement_requested = st.toggle(
                    "状态语音播报",
                    value=False,
                    key="demo_voice_announcement",
                )
                st.caption(
                    "开启：状态变化时播报"
                    if voice_announcement_requested
                    else "关闭：仅界面展示"
                )
            selected_response_mode: DemoResponseMode = (
                "AI" if response_mode == "AI" else "DIRECT"
            )
            st.markdown(
                '<p class="demo-mode-description">'
                '即时演示立即应用状态，以 SIMULATED AI TRACE 展示分析过程；'
                'AI 完整链路会等待本机 Ollama / Qwen 返回。'
                '弯腰为课堂模拟姿态，不调用真实雷达 / AI 判断链路。</p>',
                unsafe_allow_html=True,
            )
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
            st.markdown(
                f'<p class="demo-resident-source">{escape(source_text)}</p>',
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div class="demo-control-section-title demo-action-title"><div>'
            '<span>场景操作</span><strong>注入一次演示状态</strong></div>'
            '<small>跌倒场景会触发完整告警流程</small></div>',
            unsafe_allow_html=True,
        )

        actions: tuple[tuple[str, DemoAction, str], ...] = (
            ("发送正常数据", "NORMAL", ":material/check_circle:"),
            ("发送跌倒数据", "FALL", ":material/warning:"),
            ("发送疑似异常", "WARNING", ":material/error:"),
            ("模拟弯腰", "BEND", ":material/accessibility_new:"),
            ("模拟设备离线", "OFFLINE", ":material/link_off:"),
            ("恢复正常", "RECOVER", ":material/restart_alt:"),
            ("确认报警", "ACKNOWLEDGE", ":material/done_all:"),
        )
        action_rows = (actions[:4], actions[4:])
        for action_row in action_rows:
            columns = st.columns(len(action_row), gap="small")
            for column, (label, action, icon) in zip(columns, action_row):
                with column:
                    if st.button(
                        label,
                        key=f"demo-action-{action}",
                        icon=icon,
                        width="stretch",
                    ):
                        result = _execute_demo_action(
                            controller,
                            selected_id,
                            action,
                            response_mode=selected_response_mode,
                            voice_announcement_requested=voice_announcement_requested,
                        )
                        st.session_state["demo_last_result"] = result
                        st.rerun()

        _render_demo_result(st.session_state.get("demo_last_result"))

    _render_demo_current_state(controller, selected_id)


@st.fragment(run_every=0.5)
def _render_demo_current_state(
    controller: CommunityController,
    resident_id: str,
) -> None:
    """Refresh applied runtime state without replaying control side effects."""

    states = controller.states()
    with st.container(key="demo-current-state"):
        _render_demo_state(controller, states[resident_id])


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
    current_alerts = sum(state.status == "FALL" for state in states.values())
    statistics = (
        ("监护住户", len(controller.registry.residents), "stat-secondary"),
        (
            "在线设备",
            sum(state.status != "OFFLINE" for state in states.values()),
            "stat-tertiary",
        ),
        (
            "正常住户",
            sum(
                state.status in {"NORMAL", "RECOVERED"}
                and state.posture_event == "NONE"
                for state in states.values()
            ),
            "stat-success",
        ),
        (
            "当前报警",
            current_alerts,
            "stat-error" if current_alerts > 0 else "stat-neutral",
        ),
        (
            "今日报警",
            today_alerts,
            "stat-warning",
        ),
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
        state = states[res.id]
        st_val = state.status
        if selected_filter == "全部":
            return True
        if selected_filter == "正常":
            return st_val in {"NORMAL", "RECOVERED"} and state.posture_event == "NONE"
        if selected_filter == "关注":
            return st_val in {"FALL", "WARNING"} or state.posture_event == "BEND"
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
            visual_state = "bend" if state.posture_event == "BEND" else state.status.lower()
            with column:
                with st.container(
                    key=f"resident-card-{visual_state}{selected_class}-{resident.id}"
                ):
                    status_label = (
                        "弯腰姿态"
                        if state.posture_event == "BEND"
                        else STATUS_LABELS[state.status]
                    )
                    handled = " · 已确认" if state.status == "FALL" and state.handled else ""
                    time_label = _short_time(state.alarm_time or state.updated_at)
                    if selected:
                        indicator = "✓ 已选择"
                    elif state.posture_event == "BEND":
                        indicator = "● 姿态关注"
                    elif state.status in {"NORMAL", "RECOVERED"}:
                        indicator = "● 安全监护"
                    elif state.status == "FALL":
                        indicator = "● 跌倒告警"
                    elif state.status == "WARNING":
                        indicator = "▲ 疑似异常"
                    else:
                        indicator = "○ 设备离线"
                    label = (
                        f"{resident.address}\n"
                        f"**{resident.name} · {resident.age}岁**\n"
                        f"{indicator} · {status_label}{handled} · {time_label}"
                    )
                    if st.button(
                        label,
                        key=f"select-resident-{resident.id}",
                        width="stretch",
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

    st.markdown('<div class="community-action-spacer"></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3, gap="small")
    with col1:
        with st.container(key="community-bottom-btn-1"):
            if st.button(
                "查看历史报告",
                key="btn-history-report",
                icon=":material/history_edu:",
                width="stretch",
            ):
                st.toast(
                    f"【历史健康档案】已调取住户 {resident.name} ({resident.address}) 近 30 天跌倒风险与活动节律报告。",
                    icon=":material/history_edu:",
                )
    with col2:
        with st.container(key="community-bottom-btn-2"):
            if st.button(
                "联系家属",
                key="btn-contact-family",
                icon=":material/phone_in_talk:",
                width="stretch",
            ):
                st.toast(
                    f"【紧急呼叫】正在一键拨打住户 {resident.name} 的紧急联系人家属电话...",
                    icon=":material/phone_in_talk:",
                )
    with col3:
        with st.container(key="community-bottom-btn-3"):
            if st.button(
                "生成护理建议",
                key="btn-generate-advice",
                icon=":material/psychology:",
                width="stretch",
            ):
                current_status = state.status if state else "NORMAL"
                if current_status == "FALL":
                    advice = "高危跌倒事件：建议立即指派网格员上门，协助老人保持平躺并拨打 120 检查髋关节与头部。"
                elif current_status == "WARNING":
                    advice = "疑似姿态异常：建议通过室内可视对讲核实老人状态，关注防滑拖鞋与夜起照明。"
                elif state is not None and state.posture_event == "BEND":
                    advice = "检测到弯腰姿态：建议提醒老人缓慢起身，并持续关注活动状态。"
                else:
                    advice = "日常健康监护：该住户活动指标正常，建议维持每日晨间起居步态监测与室内通道无障碍防跌倒巡查。"
                st.toast(
                    f"【AI 护理建议】{advice}",
                    icon=":material/psychology:",
                )


def _render_selected_resident(
    controller: CommunityController,
    states: dict[str, ResidentState],
    events: list[dict[str, str]],
    theme: Mapping[str, str],
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
        f'{escape(kicker)}</div><h2 class="resident-detail-title">{escape(resident.address)}</h2></div>'
        f'<span class="panel-note resident-detail-note">{escape(resident.id)}<br>{escape(_business_channel(state.source))}</span></div>',
        unsafe_allow_html=True,
    )

    # 1. MD3 Status Capsule Pill at top of details
    _render_resident_status_capsule(state)

    # 2. Grid-structured parameters
    _render_resident_summary(resident, state)

    # 3. Plotly area height trend chart
    _render_resident_height_chart(state, theme)

    # Action buttons for current resident state
    action_columns = st.columns(2, gap="small")
    with action_columns[0]:
        if state.status == "FALL" and not state.handled:
            with st.container(key="community-ack-btn"):
                if st.button(
                    "确认报警",
                    key="community-acknowledge",
                    icon=":material/done_all:",
                    width="stretch",
                ):
                    _execute_demo_action(controller, resident.id, "ACKNOWLEDGE")
                    st.rerun()
        else:
            with st.container(key="community-rec-btn"):
                if st.button(
                    "恢复正常",
                    key="community-recover",
                    icon=":material/restart_alt:",
                    width="stretch",
                ):
                    _execute_demo_action(controller, resident.id, "RECOVER")
                    st.rerun()
    with action_columns[1]:
        with st.container(key="community-tech-btn"):
            if st.button(
                "查看技术详情",
                key="community-open-technical",
                icon=":material/radar:",
                width="stretch",
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
        badge_class = "danger"
        badge_text = "● 紧急跌倒报警中 · 立即调度"
    elif state.status == "WARNING":
        badge_class = "warning"
        badge_text = "▲ 疑似跌倒姿态 · 持续二次判定"
    elif state.status == "OFFLINE":
        badge_class = "offline"
        badge_text = "✕ 雷达传感器离线"
    elif state.posture_event == "BEND":
        badge_class = "posture"
        badge_text = "● 检测到弯腰姿态"
    else:
        badge_class = "safe"
        badge_text = "● 正常监护中 · 生命体征平稳"

    st.markdown(
        '<div class="resident-status-wrap">'
        f'<span class="resident-status-capsule {badge_class}">'
        f'{badge_text}</span></div>',
        unsafe_allow_html=True,
    )


def _render_resident_summary(resident: Resident, state: ResidentState) -> None:
    alarm_time = _short_time(state.alarm_time) if state.alarm_time else "--:--:--"
    radar = _result_label(state.radar_result)
    ai = _result_label(state.ai_result)
    alarm_semantic = (
        "alarm-error"
        if state.status == "FALL"
        else "alarm-warning" if state.status == "WARNING" else "neutral"
    )
    process_semantic = "process-success" if state.handled else "neutral"
    posture = "弯腰" if state.posture_event == "BEND" else "无"
    rows = [
        ("老人姓名", resident.name, "identity"),
        ("年龄", f"{resident.age} 岁", "identity"),
        ("雷达状态", radar, "radar"),
        ("AI 智能研判", ai, "ai"),
        ("推理模型", _business_model(state.ai_model), "model"),
        ("报警时间", alarm_time, alarm_semantic),
        (
            "处理状态",
            "已确认" if state.handled else "待处理",
            process_semantic,
        ),
        ("数据信道", _business_channel(state.source), "channel"),
        ("姿态事件", posture, "posture"),
    ]

    items_html = "".join(
        f'<div class="resident-summary-item resident-summary-{semantic}">'
        f'<span>{escape(label)}</span>'
        f'<strong>{escape(str(value))}</strong>'
        f'</div>'
        for label, value, semantic in rows
    )
    st.markdown(
        '<div class="resident-summary-grid">'
        f'{items_html}</div>',
        unsafe_allow_html=True,
    )


def _render_resident_height_chart(
    state: ResidentState,
    theme: Mapping[str, str],
) -> None:
    st.markdown(
        '<div class="resident-chart-heading">'
        '<span>'
        '雷达人体离地高度走势 (30s)</span>'
        '<strong>毫米波微动追踪</strong>'
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
        elif state.posture_event == "BEND":
            if i < 12:
                height = 1.46 + 0.04 * ((i % 4) - 1.5)
            elif i < 20:
                decay = (i - 12) / 8.0
                height = 1.46 * (1.0 - decay) + 0.90 * decay
            else:
                height = 0.90 + 0.05 * ((i % 3) - 1)
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
            line=dict(color=theme["secondary"], width=3.5, shape="spline"),
            fill="tozeroy",
            fillcolor=_color_with_alpha(theme["secondary"], 0.14),
            name="离地高度",
            hovertemplate="%{x|%H:%M:%S}<br>高度: %{y:.2f} m<extra></extra>",
        )
    )
    fig.add_hline(
        y=0.4,
        line_dash="dash",
        line_color=theme["danger"],
        line_width=2,
        annotation_text="跌倒警戒线 (0.4m)",
        annotation_position="top left",
        annotation_font=dict(size=10, color=theme["danger"], family="sans-serif"),
    )
    fig.update_layout(
        height=135,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor=theme["surface_container_high"],
        plot_bgcolor=theme["surface_container_high"],
        xaxis=dict(
            showgrid=True,
            gridcolor=theme["chart_grid"],
            gridwidth=1,
            griddash="dot",
            tickformat="%H:%M:%S",
            tickfont=dict(size=10, color=theme["muted"]),
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=theme["chart_grid"],
            gridwidth=1,
            griddash="dot",
            range=[0.0, 2.0],
            tickfont=dict(size=10, color=theme["muted"]),
            zeroline=False,
        ),
        hoverlabel=dict(
            bgcolor=theme["surface_container_highest"],
            bordercolor=theme["outline"],
            font=dict(color=theme["ink"]),
        ),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _color_with_alpha(color: str, alpha: float) -> str:
    """Convert a palette hex color to an rgba value for Plotly fills."""

    normalized = color.removeprefix("#")
    if len(normalized) != 6:
        return color
    try:
        red, green, blue = (
            int(normalized[index : index + 2], 16) for index in (0, 2, 4)
        )
    except ValueError:
        return color
    return f"rgba({red}, {green}, {blue}, {alpha:.2f})"


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
    *,
    response_mode: DemoResponseMode | None = None,
    voice_announcement_requested: bool = False,
) -> DemoControlResult:
    return DemoControlService(controller).execute(
        resident_id,
        action,
        response_mode=response_mode,
        voice_announcement_requested=voice_announcement_requested,
    )


def _render_demo_result(result: object) -> None:
    if not isinstance(result, DemoControlResult):
        return
    if result.ai_result is None:
        mode = result.state.demo_response_mode or "DIRECT"
        if result.action == "BEND":
            mode_label = "模拟弯腰姿态 · DEMO ONLY"
        else:
            mode_label = (
                "即时演示 · SIMULATED AI TRACE"
                if mode == "DIRECT"
                else "AI完整链路 · REAL AI"
            )
        st.success(
            f"场景请求已写入：{result.action} · {mode_label}，后台监测服务正在应用。"
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
        '<div class="section-heading compact"><div><div class="section-kicker">当前状态</div>'
        f'<h2>{escape(resident.address)} · {escape(resident.name)}</h2></div>'
        f'<span>{escape(state.source)} · {_short_time(state.updated_at)}</span></div>',
        unsafe_allow_html=True,
    )
    _render_resident_summary(resident, state)
    mode = state.demo_response_mode or "DIRECT"
    if state.posture_event == "BEND":
        trace = "SIMULATED POSTURE EVENT"
        mode_label = "模拟弯腰姿态"
    else:
        trace = "SIMULATED AI TRACE" if mode == "DIRECT" else "REAL AI"
        mode_label = "即时演示" if mode == "DIRECT" else "AI完整链路"
    st.markdown(
        '<div class="demo-diagnostics">'
        f'<span>{escape(mode_label)} · {escape(mode)}</span>'
        f'<span>{escape(trace)}</span>'
        f'<span>判定来源 · {escape(state.source)}</span>'
        f'<span>状态语音 · {"开启" if state.voice_announcement_requested else "关闭"}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def _render_runtime_health() -> None:
    health = CommunityRuntimeHealthStore(
        os.getenv("LD6002C_COMMUNITY_RUNTIME_PATH", str(DEFAULT_COMMUNITY_RUNTIME_PATH))
    ).read()
    st.markdown(
        '<div class="section-heading compact"><div><div class="section-kicker">运行健康</div>'
        '<h2>后台服务状态</h2></div></div>',
        unsafe_allow_html=True,
    )
    values = (
        ("Community Runtime", health.runtime, _runtime_health_tone(health.runtime)),
        ("Ollama", health.ollama, _ollama_health_tone(health.ollama)),
        ("Model", health.model, "health-model"),
        ("Telemetry", health.telemetry, _telemetry_health_tone(health.telemetry)),
        ("Alarm", health.alarm, _alarm_health_tone(health.alarm)),
        (
            "Voice Backend",
            _voice_health_label(health.voice),
            _voice_health_tone(health.voice),
        ),
    )
    cells = "".join(
        '<div class="demo-health-cell '
        f'{tone}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
        for label, value, tone in values
    )
    st.markdown(
        f'<div class="demo-health-grid">{cells}</div>',
        unsafe_allow_html=True,
    )
    ai_time = _short_time_value(health.last_ai_success or "")
    st.markdown(
        '<div class="demo-health-meta">'
        f'<span>演示响应 · {escape(health.demo_response_mode)}</span>'
        f'<span>AI 后端 · {escape(health.ai_mode)}</span>'
        f'<span>最近真实 AI 响应 · {escape(ai_time)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    if health.last_ai_error:
        st.markdown(
            '<div class="demo-health-banner warning"><strong>AI 后端提示</strong>'
            f'<span>{escape(health.last_ai_error)}</span></div>',
            unsafe_allow_html=True,
        )
    if health.last_runtime_error:
        st.markdown(
            '<div class="demo-health-banner error"><strong>Runtime 异常</strong>'
            f'<span>{escape(health.last_runtime_error)}</span></div>',
            unsafe_allow_html=True,
        )
    if health.voice == "CONSOLE":
        st.caption("未检测到可用中文语音，仅控制台输出。")
    elif health.voice == "UNAVAILABLE":
        st.caption("语音播报后端不可用，仅保留控制台文本输出。")


def _runtime_health_tone(value: str) -> str:
    if value == "RUNNING":
        return "health-success"
    if value in {"FAILED", "ERROR", "STOPPED"}:
        return "health-error"
    return "health-neutral"


def _ollama_health_tone(value: str) -> str:
    if value == "ONLINE":
        return "health-success"
    if value == "OFFLINE":
        return "health-warning"
    return "health-neutral"


def _telemetry_health_tone(value: str) -> str:
    return "health-tertiary" if value == "ACTIVE" else "health-neutral"


def _alarm_health_tone(value: str) -> str:
    return "health-primary" if value == "READY" else "health-neutral"


def _voice_health_tone(value: str) -> str:
    return "health-tertiary" if value == "READY" else "health-neutral"


def _voice_health_label(value: str) -> str:
    return {
        "READY": "Windows 中文语音可用",
        "CONSOLE": "未检测到可用中文语音，仅控制台输出",
        "UNAVAILABLE": "语音后端不可用，仅控制台输出",
    }.get(value, value)


def _result_label(value: int | None) -> str:
    if value is None:
        return "--"
    return "FALL · 1" if value else "NORMAL · 0"


def _business_model(value: str | None) -> str:
    if value == "demo-direct":
        return "AI 分析演示"
    if value in {None, "", "fallback", "disabled", "not-requested"}:
        return "本地安全规则"
    return value


def _business_channel(source: str) -> str:
    normalized = source.strip().upper()
    if normalized.startswith("LD6002C"):
        return "LD6002C 毫米波雷达"
    if normalized == "INITIAL":
        return "等待监护数据"
    return "社区安全监护"


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
