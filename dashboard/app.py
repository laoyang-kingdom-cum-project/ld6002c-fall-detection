"""Streamlit presentation wall for the LD6002C teaching project."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
import os
from pathlib import Path
from typing import Mapping

import altair as alt
import pandas as pd
import streamlit as st

try:
    from dashboard.community_ui import (
        render_community_dashboard,
        render_demo_console,
    )
except ModuleNotFoundError as exc:
    if exc.name != "dashboard":
        raise
    from community_ui import (  # type: ignore[no-redef]
        render_community_dashboard,
        render_demo_console,
    )
from ld6002c_fall.ai.ollama_client import disabled_ai_result
from ld6002c_fall.community import CommunityController, CommunityTelemetryStore
from ld6002c_fall.config import (
    DEFAULT_COMMUNITY_CONFIG_PATH,
    DEFAULT_COMMUNITY_EVENT_PATH,
    DEFAULT_COMMUNITY_STATE_PATH,
    DEFAULT_COMMUNITY_TELEMETRY_DIR,
)
from ld6002c_fall.csv_snapshot import CSVSnapshotError, read_csv_tail
from ld6002c_fall.live_monitor import (
    AIChatEntry,
    AxisHistoryEntry,
    MonitorSnapshot,
    PointHistoryEntry,
    SensorStreamEntry,
    build_ai_chat,
    build_axis_history,
    build_monitor_snapshot,
    build_point_history,
    build_sensor_stream,
    point_cloud_status,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = Path(os.getenv("LD6002C_LOG_PATH", PROJECT_ROOT / "data" / "fall_log.csv"))
EVENT_LOG_PATH = Path(
    os.getenv("LD6002C_EVENT_LOG_PATH", PROJECT_ROOT / "data" / "events.csv")
)
LIVE_REFRESH_SECONDS = float(os.getenv("DASHBOARD_REFRESH_SECONDS", "2.0"))
COMMUNITY_REFRESH_SECONDS = float(os.getenv("COMMUNITY_REFRESH_SECONDS", "1.5"))
LOG_REFRESH_SECONDS = float(os.getenv("DASHBOARD_LOG_REFRESH_SECONDS", "5.0"))
DASHBOARD_MAX_ROWS = int(os.getenv("DASHBOARD_MAX_ROWS", "600"))


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    canvas: str
    surface: str
    surface_soft: str
    ink: str
    muted: str
    line: str
    header_background: str
    terra: str
    sage: str
    amber: str
    danger: str
    axis_blue: str
    chart_background: str
    chart_line: str
    chart_axis: str
    chart_grid: str
    terminal_background: str
    terminal_text: str
    terminal_line: str
    terminal_accent: str


LIGHT_PALETTE = ThemePalette(
    mode="light",
    canvas="#F4F2ED",
    surface="#FFFEFA",
    surface_soft="#F8F7F3",
    ink="#292724",
    muted="#77736D",
    line="#DEDBD3",
    header_background="rgba(244, 242, 237, 0.96)",
    terra="#C15F3C",
    sage="#607B6B",
    amber="#B17A3D",
    danger="#B7443E",
    axis_blue="#4F7188",
    chart_background="#FBFAF7",
    chart_line="#EBE8E1",
    chart_axis="#77736D",
    chart_grid="#E8E5DE",
    terminal_background="#302E2B",
    terminal_text="#E9E5DC",
    terminal_line="#494640",
    terminal_accent="#DB9A78",
)

DARK_PALETTE = ThemePalette(
    mode="dark",
    canvas="#171715",
    surface="#211F1C",
    surface_soft="#292723",
    ink="#F2EFE8",
    muted="#B4AEA4",
    line="#46423B",
    header_background="rgba(23, 23, 21, 0.96)",
    terra="#E47A55",
    sage="#8FAE98",
    amber="#D4A15E",
    danger="#EF746D",
    axis_blue="#78A6C8",
    chart_background="#1C1B18",
    chart_line="#3A3731",
    chart_axis="#C6C0B6",
    chart_grid="#3B3833",
    terminal_background="#10100F",
    terminal_text="#E8E4DC",
    terminal_line="#302F2A",
    terminal_accent="#F0A17B",
)


def _palette_for(theme_type: str | None) -> ThemePalette:
    return DARK_PALETTE if theme_type == "dark" else LIGHT_PALETTE


def _theme_palette() -> ThemePalette:
    return _palette_for(st.context.theme.type)


def _css_theme_variables() -> str:
    css_fields = (
        ("canvas", "canvas"),
        ("surface", "surface"),
        ("surface-soft", "surface_soft"),
        ("ink", "ink"),
        ("muted", "muted"),
        ("line", "line"),
        ("header-bg", "header_background"),
        ("terra", "terra"),
        ("sage", "sage"),
        ("amber", "amber"),
        ("danger", "danger"),
        ("axis-blue", "axis_blue"),
        ("chart-bg", "chart_background"),
        ("chart-line", "chart_line"),
        ("terminal-bg", "terminal_background"),
        ("terminal-text", "terminal_text"),
        ("terminal-line", "terminal_line"),
        ("terminal-accent", "terminal_accent"),
    )
    return "\n".join(
        f"--{css_name}: light-dark("
        f"{getattr(LIGHT_PALETTE, field_name)}, "
        f"{getattr(DARK_PALETTE, field_name)});"
        for css_name, field_name in css_fields
    )


def main() -> None:
    st.set_page_config(
        page_title="幸福社区 · 老人安全监测中心",
        page_icon=":material/radar:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _install_styles()
    _install_scroll_policy()
    controller = _build_community_controller()
    if controller is None:
        return
    view, resident_id = _route_from_query_params(st.query_params)
    header = {
        "community": (
            f"{controller.registry.community_name} · 老人智能安全监测中心",
            "Community Elderly Safety Monitoring Center",
            "COMMUNITY OPERATIONS",
        ),
        "control": (
            "社区安全演示控制台",
            "Classroom Scenario Injection Console",
            "DEMO CONTROL",
        ),
        "technical": (
            "LD6002C 毫米波雷达技术详情",
            "Radar, AI, Point Cloud and Raw Data",
            "TECHNICAL MONITOR",
        ),
    }[view]
    st.markdown(
        f"""
        <header class="wall-header">
          <div>
            <div class="wall-kicker">{escape(header[1])}</div>
            <h1>{escape(header[0])}</h1>
          </div>
          <div class="wall-live"><span></span> {escape(header[2])}</div>
        </header>
        """,
        unsafe_allow_html=True,
    )
    if view == "community":
        _show_community_dashboard(controller)
    elif view == "control":
        render_demo_console(controller)
    else:
        _show_technical_detail(controller, resident_id)


def _build_community_controller() -> CommunityController | None:
    try:
        return CommunityController.from_paths(
            os.getenv("LD6002C_COMMUNITY_CONFIG_PATH", str(DEFAULT_COMMUNITY_CONFIG_PATH)),
            os.getenv("LD6002C_COMMUNITY_STATE_PATH", str(DEFAULT_COMMUNITY_STATE_PATH)),
            os.getenv("LD6002C_COMMUNITY_EVENT_PATH", str(DEFAULT_COMMUNITY_EVENT_PATH)),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        st.error(f"社区监护数据初始化失败：{exc}")
        return None


def _route_from_query_params(
    params: Mapping[str, object],
) -> tuple[str, str | None]:
    """Resolve a stable URL route without session-only navigation state."""

    raw_view = params.get("view", "")
    if isinstance(raw_view, list):
        raw_view = raw_view[-1] if raw_view else ""
    view = str(raw_view).strip().lower()
    route = view if view in {"control", "technical"} else "community"
    raw_resident = params.get("resident")
    if isinstance(raw_resident, list):
        raw_resident = raw_resident[-1] if raw_resident else None
    resident_id = str(raw_resident).strip() if raw_resident else None
    return route, resident_id


@st.fragment(run_every=COMMUNITY_REFRESH_SECONDS)
def _show_community_dashboard(controller: CommunityController) -> None:
    """Refresh community state without flashing the whole Streamlit page."""

    with st.container(key="community-dashboard"):
        render_community_dashboard(controller)


def _show_technical_detail(
    controller: CommunityController,
    requested_resident_id: str | None,
) -> None:
    if st.button("返回社区大屏", icon=":material/arrow_back:", type="tertiary"):
        st.query_params.clear()
        st.rerun()
    selected_id = requested_resident_id or st.session_state.get("selected_resident_id")
    try:
        resident = controller.registry.get(str(selected_id))
    except KeyError:
        resident = controller.registry.bound_to("LD6002C")
        st.session_state["selected_resident_id"] = resident.id
    else:
        st.session_state["selected_resident_id"] = resident.id
    telemetry = CommunityTelemetryStore(
        os.getenv(
            "LD6002C_COMMUNITY_TELEMETRY_DIR",
            str(DEFAULT_COMMUNITY_TELEMETRY_DIR),
        )
    )
    frame_path, event_path, data_source, use_demo_telemetry = _technical_data_paths(
        controller,
        resident.id,
        telemetry,
    )
    if use_demo_telemetry and not telemetry.has_frames(resident.id):
        telemetry.write_scenario(
            resident.id,
            "NORMAL",
            disabled_ai_result(0),
            timestamp=datetime.now().astimezone(),
            frame_count=30,
        )
    st.markdown(
        '<div class="technical-resident-context"><strong>'
        f'{escape(resident.address)} · {escape(resident.name)} · {resident.age}岁</strong>'
        f'<span>{escape(data_source)}</span></div>',
        unsafe_allow_html=True,
    )
    _show_live_dashboard(frame_path, event_path)
    _show_logs(frame_path, event_path)


def _technical_data_paths(
    controller: CommunityController,
    resident_id: str,
    telemetry: CommunityTelemetryStore,
) -> tuple[Path, Path, str, bool]:
    """Select real or demo files from persisted resident override state."""

    resident = controller.registry.get(resident_id)
    state = controller.states()[resident_id]
    use_demo = state.demo_override or not resident.has_live_sensor
    if use_demo:
        return (
            telemetry.frame_path(resident_id),
            telemetry.event_path(resident_id),
            "SIMULATED RADAR DATA · CLASSROOM DEMO",
            True,
        )
    return LOG_PATH, EVENT_LOG_PATH, "HLK-LD6002C · REALTIME", False


def _install_styles() -> None:
    theme_variables = _css_theme_variables()
    styles = (
        """
        <style>
        :root {
            /* THEME_VARIABLES */
        }
        .stApp { background: var(--canvas); color: var(--ink); }
        [data-testid="stAppViewContainer"] { background: var(--canvas); }
        [data-testid="stHeader"] { background: var(--header-bg); }
        [data-testid="stMainBlockContainer"] {
            max-width: none;
            padding: 1rem 2rem 3rem;
            overflow-anchor: none;
        }
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] { overflow-anchor: none; }
        [data-testid="stStatusWidget"],
        [data-testid="stSpinner"] { display: none !important; }
        .st-key-live-dashboard [data-testid="stElementContainer"],
        .st-key-log-dashboard [data-testid="stElementContainer"] {
            opacity: 1 !important;
            transition: none !important;
        }
        h1, h2, h3, p, span, div { letter-spacing: 0; }
        h1 { color: var(--ink); }
        .wall-header {
            align-items: flex-end;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.8rem;
            padding: 0.4rem 0 0.9rem;
        }
        .wall-header h1 {
            font-size: 1.85rem;
            line-height: 1.15;
            margin: 0.25rem 0 0;
        }
        .wall-kicker, .section-kicker {
            color: var(--terra);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .wall-live {
            align-items: center;
            color: var(--muted);
            display: flex;
            font-size: 0.76rem;
            font-weight: 700;
            gap: 0.45rem;
            justify-content: flex-end;
            white-space: nowrap;
        }
        .wall-live span {
            background: var(--sage);
            border-radius: 50%;
            display: inline-block;
            height: 8px;
            width: 8px;
        }
        .community-stats {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            margin: 0.65rem 0 0.8rem;
        }
        .community-stat {
            background: var(--surface);
            border: 1px solid var(--line);
            border-top: 3px solid var(--sage);
            border-radius: 6px;
            padding: 0.55rem 0.75rem;
        }
        .community-stat:nth-child(4), .community-stat:nth-child(5) { border-top-color: var(--terra); }
        .community-stat span {
            color: var(--muted);
            display: block;
            font-size: 0.68rem;
            margin-bottom: 0.1rem;
        }
        .community-stat strong { display: block; font-size: 1.35rem; line-height: 1.1; }
        .section-heading {
            align-items: baseline;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.55rem;
            padding-bottom: 0.4rem;
        }
        .section-heading.compact { margin-top: 0.75rem; }
        .section-heading h2 { font-size: 1rem; margin: 0.08rem 0 0; }
        .section-heading span { color: var(--muted); font-size: 0.7rem; }
        div[class*="st-key-resident-card-"] { margin-bottom: 0.35rem; }
        div[class*="st-key-resident-card-"] button {
            background: var(--surface);
            border: 1px solid var(--line);
            border-left: 4px solid var(--sage);
            border-radius: 6px;
            color: var(--ink);
            min-height: 70px;
            padding: 0.5rem 0.6rem;
            text-align: left;
        }
        div[class*="st-key-resident-card-"] button p {
            font-size: 0.73rem;
            line-height: 1.45;
            white-space: pre-line;
        }
        div[class*="st-key-resident-card-warning"] button {
            background: color-mix(in srgb, var(--amber) 9%, var(--surface));
            border-left-color: var(--amber);
        }
        div[class*="st-key-resident-card-fall"] button {
            background: color-mix(in srgb, var(--danger) 13%, var(--surface));
            border-color: var(--danger);
            border-left-width: 5px;
            color: var(--danger);
        }
        div[class*="st-key-resident-card-offline"] button {
            background: var(--surface-soft);
            border-left-color: var(--muted);
            color: var(--muted);
        }
        div[class*="-selected-"] button { box-shadow: 0 0 0 2px var(--terra); }
        .st-key-community-detail-panel {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 6px;
            min-height: 480px;
            padding: 0.9rem;
        }
        .st-key-community-detail-panel .panel-heading {
            margin-bottom: 0.4rem;
            padding-bottom: 0.4rem;
        }
        .st-key-community-detail-panel .state-hero { padding: 0.35rem 0 0.55rem; }
        .st-key-community-detail-panel .state-value { font-size: 1.45rem; }
        .st-key-community-detail-panel .detail-row { min-height: 34px; }
        .technical-resident-context {
            align-items: center;
            background: var(--surface-soft);
            border-left: 4px solid var(--terra);
            display: flex;
            justify-content: space-between;
            margin: 0.55rem 0 0.75rem;
            padding: 0.55rem 0.75rem;
        }
        .technical-resident-context strong { font-size: 0.9rem; }
        .technical-resident-context span { color: var(--muted); font-size: 0.72rem; }
        .simulation-notice {
            background: var(--surface-soft);
            border: 1px solid var(--line);
            border-left: 4px solid var(--amber);
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            margin-bottom: 0.75rem;
            padding: 0.75rem;
        }
        .simulation-notice span { color: var(--muted); font-size: 0.78rem; }
        .monitor-status-grid {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            margin: 0.7rem 0;
        }
        .monitor-status-item {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 6px;
            min-width: 0;
            padding: 0.65rem 0.75rem;
        }
        .monitor-status-item.connected { border-top: 3px solid var(--sage); }
        .monitor-status-item.warning { border-top: 3px solid var(--amber); }
        .monitor-status-item.danger { border-top: 3px solid var(--danger); }
        .monitor-status-label {
            color: var(--muted);
            display: block;
            font-size: 0.68rem;
            margin-bottom: 0.28rem;
            text-transform: uppercase;
        }
        .monitor-status-value {
            color: var(--ink);
            display: block;
            font-size: 0.94rem;
            line-height: 1.2;
            overflow-wrap: anywhere;
        }
        .current-alert {
            align-items: center;
            background: var(--surface-soft);
            border-left: 4px solid var(--sage);
            display: flex;
            font-size: 0.88rem;
            min-height: 38px;
            padding: 0.45rem 0.75rem;
        }
        .current-alert.warning { border-left-color: var(--amber); }
        .current-alert.danger { border-left-color: var(--danger); color: var(--danger); }
        .st-key-overview-panel,
        .st-key-coordinate-panel,
        .st-key-ai-panel {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 6px;
            min-height: 550px;
            padding: 1rem;
        }
        .st-key-axis-trend-panel {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 6px;
            margin-top: 0.8rem;
            padding: 1rem;
        }
        .panel-heading {
            align-items: flex-start;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.8rem;
            padding-bottom: 0.65rem;
        }
        .panel-heading h2 {
            font-size: 1.05rem;
            line-height: 1.2;
            margin: 0.16rem 0 0;
        }
        .panel-note { color: var(--muted); font-size: 0.7rem; text-align: right; }
        .state-hero { padding: 0.8rem 0 1rem; }
        .state-label { color: var(--muted); font-size: 0.72rem; }
        .state-value {
            color: var(--ink);
            font-size: 1.8rem;
            font-weight: 650;
            line-height: 1.2;
            margin-top: 0.25rem;
            overflow-wrap: anywhere;
        }
        .state-value.danger { color: var(--danger); }
        .state-value.warning { color: var(--amber); }
        .detail-list { border-top: 1px solid var(--line); }
        .detail-row {
            align-items: center;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            min-height: 45px;
        }
        .detail-row span { color: var(--muted); font-size: 0.76rem; }
        .detail-row strong { font-size: 0.86rem; overflow-wrap: anywhere; text-align: right; }
        .coordinate-stats, .ai-meta-grid {
            border-bottom: 1px solid var(--line);
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin-bottom: 0.65rem;
        }
        .coordinate-stat, .ai-meta-item {
            border-right: 1px solid var(--line);
            min-width: 0;
            padding: 0.35rem 0.55rem 0.55rem;
        }
        .coordinate-stat:first-child, .ai-meta-item:first-child { padding-left: 0; }
        .coordinate-stat:last-child, .ai-meta-item:last-child { border-right: 0; }
        .coordinate-stat span, .ai-meta-item span {
            color: var(--muted);
            display: block;
            font-size: 0.66rem;
            margin-bottom: 0.15rem;
        }
        .coordinate-stat strong, .ai-meta-item strong {
            display: block;
            font-size: 0.86rem;
            overflow-wrap: anywhere;
        }
        .projection-label {
            color: var(--muted);
            font-size: 0.68rem;
            font-weight: 700;
            margin: 0.2rem 0 0;
            text-transform: uppercase;
        }
        .axis-trend-stats {
            border-bottom: 1px solid var(--line);
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin-bottom: 0.55rem;
        }
        .axis-trend-stat {
            border-right: 1px solid var(--line);
            min-width: 0;
            padding: 0.3rem 0.65rem 0.5rem;
        }
        .axis-trend-stat:first-child { padding-left: 0; }
        .axis-trend-stat:last-child { border-right: 0; }
        .axis-trend-stat span {
            color: var(--muted);
            display: block;
            font-size: 0.66rem;
            margin-bottom: 0.12rem;
        }
        .axis-trend-stat strong { display: block; font-size: 0.88rem; }
        .axis-trend-stat.x strong { color: var(--terra); }
        .axis-trend-stat.y strong { color: var(--sage); }
        .axis-trend-stat.z strong { color: var(--axis-blue); }
        .axis-trend-empty {
            align-items: center;
            background: var(--chart-bg);
            border: 1px dashed var(--line);
            color: var(--muted);
            display: flex;
            justify-content: center;
            min-height: 220px;
        }
        [data-testid="stVegaLiteChart"] {
            background: var(--chart-bg);
            border: 1px solid var(--chart-line);
            border-radius: 4px;
        }
        details[title="Click to view actions"] { display: none; }
        .coordinate-empty {
            align-items: center;
            background: var(--chart-bg);
            border: 1px dashed var(--line);
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-height: 410px;
            text-align: center;
        }
        .coordinate-empty strong { font-size: 1rem; }
        .coordinate-empty span { color: var(--muted); font-size: 0.76rem; margin-top: 0.35rem; }
        .ai-entry {
            border-bottom: 1px solid var(--line);
            padding: 0.72rem 0;
        }
        .ai-entry:last-child { border-bottom: 0; }
        .ai-entry-head { align-items: center; display: flex; justify-content: space-between; gap: 0.5rem; }
        .ai-entry-status { color: var(--sage); font-size: 0.7rem; font-weight: 750; }
        .ai-entry-status.danger { color: var(--danger); }
        .ai-entry-status.warning { color: var(--amber); }
        .ai-entry-time { color: var(--muted); font-size: 0.68rem; }
        .ai-entry p { font-size: 0.82rem; line-height: 1.45; margin: 0.35rem 0; }
        .ai-entry-meta { color: var(--muted); font-size: 0.68rem; overflow-wrap: anywhere; }
        .subsection-heading {
            align-items: baseline;
            border-bottom: 1px solid var(--line);
            display: flex;
            justify-content: space-between;
            margin: 1.1rem 0 0.55rem;
            padding-bottom: 0.45rem;
        }
        .subsection-heading h2 { font-size: 1rem; margin: 0; }
        .subsection-heading span { color: var(--muted); font-size: 0.7rem; }
        .sensor-lines {
            background: var(--terminal-bg);
            color: var(--terminal-text);
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.7rem;
            line-height: 1.6;
            min-height: 250px;
            overflow-wrap: anywhere;
            padding: 0.75rem;
        }
        .sensor-line { border-bottom: 1px solid var(--terminal-line); padding: 0.18rem 0; }
        .sensor-line:last-child { border-bottom: 0; }
        .sensor-line b { color: var(--terminal-accent); font-weight: 600; }
        [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 4px; }
        [data-baseweb="tab-list"] { gap: 0.2rem; }
        [data-baseweb="tab"] { letter-spacing: 0; }
        #vg-tooltip-element.vg-tooltip {
            background: var(--surface) !important;
            border-color: var(--line) !important;
            color: var(--ink) !important;
        }
        @media (max-width: 1100px) {
            [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; }
            .monitor-status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .community-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .st-key-overview-panel,
            .st-key-coordinate-panel,
            .st-key-ai-panel { min-height: auto; }
        }
        @media (max-width: 700px) {
            .wall-header { align-items: flex-start; gap: 0.8rem; }
            .wall-header h1 { font-size: 1.45rem; }
            .wall-live { margin-top: 0.3rem; }
            .monitor-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .community-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .coordinate-stats, .ai-meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .axis-trend-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .coordinate-stat:nth-child(2), .ai-meta-item:nth-child(2) { border-right: 0; }
            .axis-trend-stat:nth-child(2) { border-right: 0; }
            .coordinate-stat, .ai-meta-item { border-bottom: 1px solid var(--line); }
            .axis-trend-stat { border-bottom: 1px solid var(--line); }
            .state-value { font-size: 1.45rem; }
        }
        </style>
        """
        .replace("/* THEME_VARIABLES */", theme_variables)
    )
    st.markdown(styles, unsafe_allow_html=True)


@st.fragment(run_every=LIVE_REFRESH_SECONDS)
def _show_live_dashboard(frame_path: Path, event_path: Path) -> None:
    """Refresh live panels without rebuilding the heavier log tables."""

    with st.container(key="live-dashboard"):
        _render_live_dashboard(frame_path, event_path)


def _render_live_dashboard(frame_path: Path, event_path: Path) -> None:
    frame_data = _read_csv(frame_path)
    if frame_data is None:
        st.info("还没有监测日志，请先运行 ld6002c-fall 主程序。")
        return
    if frame_data.empty:
        st.info("监测日志为空，正在等待第一帧雷达数据。")
        return

    event_data = _read_csv(event_path, missing_ok=True)
    if event_data is None:
        event_data = pd.DataFrame()
    frame_data = _ensure_monitor_columns(frame_data)
    frame_rows = frame_data.to_dict("records")
    event_rows = event_data.to_dict("records")
    snapshot = build_monitor_snapshot(frame_rows, event_rows)
    point_history = build_point_history(frame_rows, max_frames=40)
    axis_history = build_axis_history(point_history, max_samples=40)
    cloud_status = point_cloud_status(
        point_history,
        stale_seconds=max(5.0, LIVE_REFRESH_SECONDS * 2.5),
    )
    if snapshot.radar_status == "DISCONNECTED":
        cloud_status = "DISCONNECTED"
    elif snapshot.source == "SIMULATED RADAR DATA · CLASSROOM DEMO" and point_history:
        cloud_status = "LIVE"

    _show_status_bar(snapshot, cloud_status)
    _show_current_alert(snapshot.current_status)

    overview_col, coordinate_col, ai_col = st.columns([0.78, 1.72, 1.05], gap="medium")
    with overview_col:
        with st.container(key="overview-panel"):
            _show_overview(snapshot, frame_data.iloc[-1])
    with coordinate_col:
        with st.container(key="coordinate-panel"):
            _show_coordinates(point_history, snapshot.source)
    with ai_col:
        with st.container(key="ai-panel"):
            _show_ai_panel(frame_data.iloc[-1], snapshot, event_rows)

    with st.container(key="axis-trend-panel"):
        _show_axis_trends(axis_history, snapshot.source)

    st.markdown(
        '<div class="subsection-heading"><h2>实时数据总线</h2>'
        f'<span>{escape(snapshot.source)} · 每 {LIVE_REFRESH_SECONDS:g} 秒刷新 · '
        f'{datetime.now().astimezone():%H:%M:%S}</span></div>',
        unsafe_allow_html=True,
    )
    stream = build_sensor_stream(frame_rows[-80:], event_rows[-80:], max_items=80)
    _show_sensor_stream(stream)


def _show_status_bar(snapshot: MonitorSnapshot, cloud_status: str) -> None:
    human_status = (
        "UNKNOWN"
        if snapshot.radar_status == "DISCONNECTED"
        else ("PRESENT" if snapshot.human_present else "NONE")
    )
    items = [
        ("Radar Link", snapshot.radar_status),
        ("Point Cloud", cloud_status),
        ("System State", snapshot.current_status),
        ("Human", human_status),
        ("AI Engine", snapshot.ollama_status),
        ("Data Source", snapshot.source),
    ]
    cards = "".join(
        '<div class="monitor-status-item '
        f'{_status_class(value)}"><span class="monitor-status-label">'
        f'{escape(label)}</span><strong class="monitor-status-value">'
        f"{escape(value)}</strong></div>"
        for label, value in items
    )
    st.markdown(f'<div class="monitor-status-grid">{cards}</div>', unsafe_allow_html=True)


def _show_current_alert(status: str) -> None:
    if status == "CONFIRMED_FALL":
        css_class, message = "danger", "跌倒已确认，报警流程已触发。"
    elif status == "SUSPECTED_FALL":
        css_class, message = "warning", "持续检测到跌倒信号，正在等待最终确认。"
    elif status == "OBSERVING":
        css_class, message = "warning", "系统正在观察并分析最新雷达数据。"
    elif status == "DISCONNECTED":
        css_class, message = "warning", "实时数据已断开，正在等待主程序。"
    elif status == "NO_PERSON":
        css_class, message = "", "当前区域无人，监测链路保持运行。"
    else:
        css_class, message = "", "系统状态正常，正在持续监测。"
    st.markdown(
        f'<div class="current-alert {css_class}">{escape(message)}</div>',
        unsafe_allow_html=True,
    )


def _show_overview(snapshot: MonitorSnapshot, latest: pd.Series) -> None:
    state_label = {
        "NORMAL": "正常监测",
        "NO_PERSON": "区域无人",
        "OBSERVING": "观察分析中",
        "SUSPECTED_FALL": "疑似跌倒",
        "CONFIRMED_FALL": "确认跌倒",
        "CANCELLED": "报警已取消",
        "DISCONNECTED": "数据已断开",
    }.get(snapshot.current_status, snapshot.current_status)
    state_class = _status_class(snapshot.current_status)
    human_value = "数据过期" if snapshot.radar_status == "DISCONNECTED" else (
        "是" if snapshot.human_present else "否"
    )
    rows = [
        ("人体存在", human_value),
        ("雷达跌倒信号", _result(latest.get("radar_is_fall"))),
        ("AI 最终判断", _result(latest.get("final_result"))),
        ("运动状态", snapshot.motion_state),
        ("Python 状态机", _text(latest.get("system_state")) or "未知"),
        ("报警输出", "电脑语音"),
        ("最新数据", _short_time(snapshot.last_update)),
    ]
    details = "".join(
        f'<div class="detail-row"><span>{escape(label)}</span>'
        f'<strong>{escape(value)}</strong></div>'
        for label, value in rows
    )
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">Detection</div>'
        '<h2>检测状态总览</h2></div><span class="panel-note">二次判断状态机</span></div>'
        f'<div class="state-hero"><div class="state-label">CURRENT STATE</div>'
        f'<div class="state-value {state_class}">{escape(state_label)}</div></div>'
        f'<div class="detail-list">{details}</div>',
        unsafe_allow_html=True,
    )


def _show_coordinates(point_history: list[PointHistoryEntry], source: str) -> None:
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">Spatial Tracking</div>'
        '<h2>X / Y / Z 实时点云投影</h2></div>'
        f'<span class="panel-note">{escape(source)}<br>单位：m</span></div>',
        unsafe_allow_html=True,
    )
    if not point_history:
        empty_note = (
            "模拟设备已离线，恢复后将重新生成连续点云"
            if source == "SIMULATED RADAR DATA · CLASSROOM DEMO"
            else "串口模式仅展示 LD6002C 实际 0x0A08 数据"
        )
        st.markdown(
            '<div class="coordinate-empty"><strong>等待坐标点云</strong>'
            f'<span>{escape(empty_note)}</span></div>',
            unsafe_allow_html=True,
        )
        return

    history = pd.DataFrame([asdict(entry) for entry in point_history])
    latest_cloud = history[history["is_latest_cloud"]]
    center = latest_cloud[["x", "y", "z"]].mean()
    mean_speed = latest_cloud["speed"].abs().mean()
    stats = [
        ("X CENTER", f'{center["x"]:+.2f} m'),
        ("Y CENTER", f'{center["y"]:+.2f} m'),
        ("Z CENTER", f'{center["z"]:+.2f} m'),
        ("POINTS / SPEED", f"{len(latest_cloud)} / {mean_speed:.2f} m/s"),
    ]
    stats_html = "".join(
        f'<div class="coordinate-stat"><span>{escape(label)}</span>'
        f'<strong>{escape(value)}</strong></div>'
        for label, value in stats
    )
    st.markdown(f'<div class="coordinate-stats">{stats_html}</div>', unsafe_allow_html=True)

    st.markdown('<div class="projection-label">Front projection · X / Z</div>', unsafe_allow_html=True)
    st.altair_chart(_projection_chart(history, "x", "z", 245), width="stretch")
    xy_col, yz_col = st.columns(2, gap="small")
    with xy_col:
        st.markdown('<div class="projection-label">Top · X / Y</div>', unsafe_allow_html=True)
        st.altair_chart(_projection_chart(history, "x", "y", 125), width="stretch")
    with yz_col:
        st.markdown('<div class="projection-label">Side · Y / Z</div>', unsafe_allow_html=True)
        st.altair_chart(_projection_chart(history, "y", "z", 125), width="stretch")


def _projection_chart(
    data: pd.DataFrame,
    x_field: str,
    y_field: str,
    height: int,
    palette: ThemePalette | None = None,
) -> alt.Chart:
    palette = palette or _theme_palette()
    x_domain = _axis_domain(data[x_field], x_field)
    y_domain = _axis_domain(data[y_field], y_field)
    return (
        alt.Chart(data)
        .mark_circle(stroke=palette.surface, strokeWidth=0.7)
        .encode(
            x=alt.X(
                f"{x_field}:Q",
                title=f"{x_field.upper()} (m)",
                scale=alt.Scale(domain=x_domain, nice=False),
            ),
            y=alt.Y(
                f"{y_field}:Q",
                title=f"{y_field.upper()} (m)",
                scale=alt.Scale(domain=y_domain, nice=False),
            ),
            color=alt.condition(
                alt.datum.is_latest_cloud,
                alt.value(palette.terra),
                alt.value(palette.sage),
            ),
            opacity=alt.condition(alt.datum.is_latest_cloud, alt.value(0.95), alt.value(0.12)),
            size=alt.condition(alt.datum.is_latest_cloud, alt.value(95), alt.value(28)),
            tooltip=[
                alt.Tooltip("timestamp:N", title="时间"),
                alt.Tooltip("cluster_id:Q", title="聚类 ID"),
                alt.Tooltip("x:Q", title="X", format=".3f"),
                alt.Tooltip("y:Q", title="Y", format=".3f"),
                alt.Tooltip("z:Q", title="Z", format=".3f"),
                alt.Tooltip("speed:Q", title="速度", format=".3f"),
            ],
        )
        .properties(height=height, background=palette.chart_background)
        .configure_axis(
            domainColor=palette.chart_axis,
            gridColor=palette.chart_grid,
            labelColor=palette.chart_axis,
            tickColor=palette.chart_axis,
            titleColor=palette.ink,
            titleFontWeight=500,
        )
        .configure_view(fill=palette.chart_background, stroke=None)
    )


def _show_axis_trends(samples: list[AxisHistoryEntry], source: str) -> None:
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">Motion Timeline</div>'
        '<h2>实时 XYZ 坐标轴线图</h2></div>'
        f'<span class="panel-note">{escape(source)}<br>点云质心 · 最近 40 帧</span></div>',
        unsafe_allow_html=True,
    )
    if not samples:
        st.markdown(
            '<div class="axis-trend-empty">等待点云坐标后生成轴线轨迹</div>',
            unsafe_allow_html=True,
        )
        return

    data = pd.DataFrame([asdict(sample) for sample in samples])
    data["time"] = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    data = data.dropna(subset=["time"])
    if data.empty:
        st.markdown(
            '<div class="axis-trend-empty">坐标时间戳无法解析</div>',
            unsafe_allow_html=True,
        )
        return

    latest = data.iloc[-1]
    stats = [
        ("x", "X AXIS", f'{latest["x"]:+.2f} m'),
        ("y", "Y AXIS", f'{latest["y"]:+.2f} m'),
        ("z", "Z AXIS", f'{latest["z"]:+.2f} m'),
        ("", "SAMPLES / POINTS", f'{len(data)} / {int(latest["point_count"])}'),
    ]
    stats_html = "".join(
        f'<div class="axis-trend-stat {css_class}"><span>{escape(label)}</span>'
        f'<strong>{escape(value)}</strong></div>'
        for css_class, label, value in stats
    )
    st.markdown(f'<div class="axis-trend-stats">{stats_html}</div>', unsafe_allow_html=True)

    lines = data.melt(
        id_vars=["time", "timestamp", "point_count", "mean_speed"],
        value_vars=["x", "y", "z"],
        var_name="axis",
        value_name="position",
    )
    lines["axis"] = lines["axis"].str.upper()
    st.altair_chart(_axis_trend_chart(lines), width="stretch")


def _axis_trend_chart(
    data: pd.DataFrame,
    palette: ThemePalette | None = None,
) -> alt.Chart:
    palette = palette or _theme_palette()
    domain = _trend_domain(data["position"])
    chart = (
        alt.Chart(data)
        .mark_line(point=alt.OverlayMarkDef(size=34), strokeWidth=2)
        .encode(
            x=alt.X(
                "time:T",
                title="TIME",
                axis=alt.Axis(format="%H:%M:%S", labelOverlap=True, tickCount=8),
            ),
            y=alt.Y(
                "position:Q",
                title="POSITION (m)",
                scale=alt.Scale(domain=domain, nice=False),
            ),
            color=alt.Color(
                "axis:N",
                title=None,
                scale=alt.Scale(
                    domain=["X", "Y", "Z"],
                    range=[palette.terra, palette.sage, palette.axis_blue],
                ),
                legend=alt.Legend(orient="top", direction="horizontal"),
            ),
            tooltip=[
                alt.Tooltip("timestamp:N", title="时间"),
                alt.Tooltip("axis:N", title="坐标轴"),
                alt.Tooltip("position:Q", title="位置 (m)", format="+.3f"),
                alt.Tooltip("point_count:Q", title="点数"),
                alt.Tooltip("mean_speed:Q", title="平均速度", format=".3f"),
            ],
        )
        .properties(height=220, background=palette.chart_background)
        .configure_axis(
            domainColor=palette.chart_axis,
            gridColor=palette.chart_grid,
            labelColor=palette.chart_axis,
            tickColor=palette.chart_axis,
            titleColor=palette.ink,
            titleFontWeight=500,
        )
        .configure_legend(
            labelColor=palette.ink,
            symbolStrokeWidth=3,
            titleColor=palette.ink,
        )
        .configure_view(fill=palette.chart_background, stroke=None)
    )
    return chart


def _show_ai_panel(
    latest: pd.Series,
    snapshot: MonitorSnapshot,
    events: list[dict[str, object]],
) -> None:
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">Local Intelligence</div>'
        '<h2>AI 判断流</h2></div>'
        f'<span class="panel-note">{escape(snapshot.ai_model)}<br>{escape(snapshot.ai_work_state)}</span></div>',
        unsafe_allow_html=True,
    )
    latest_ai_event = next(
        (
            row
            for row in reversed(events)
            if _text(row.get("event")) in {"AI_RESPONSE", "AI_ERROR", "AI_FALLBACK"}
        ),
        {},
    )
    meta = [
        ("RADAR", _result(latest.get("radar_is_fall"))),
        ("AI", _result(latest.get("ai_result"))),
        ("LATENCY", _inference(latest)),
        ("LAST", _short_time(_text(latest_ai_event.get("timestamp")))),
    ]
    meta_html = "".join(
        f'<div class="ai-meta-item"><span>{escape(label)}</span>'
        f'<strong>{escape(value)}</strong></div>'
        for label, value in meta
    )
    st.markdown(f'<div class="ai-meta-grid">{meta_html}</div>', unsafe_allow_html=True)
    entries = build_ai_chat(events, max_items=100)
    _show_ai_timeline(entries)


def _show_ai_timeline(entries: list[AIChatEntry]) -> None:
    if not entries:
        st.markdown(
            '<div class="coordinate-empty"><strong>等待 AI 判断</strong>'
            '<span>首次请求完成后在此显示判断链</span></div>',
            unsafe_allow_html=True,
        )
        return

    blocks = []
    for entry in reversed(entries[-7:]):
        css_class = ""
        if entry.status in {"FALL_DETECTED", "ALARM_TRIGGERED"}:
            css_class = "danger"
        elif entry.status in {"ANALYZING", "FALLBACK"}:
            css_class = "warning"
        result = "--" if entry.result is None else str(entry.result)
        latency = (
            f"{entry.inference_ms:.1f} ms" if entry.inference_ms is not None else "waiting"
        )
        repeat = f" · merged {entry.occurrences}" if entry.occurrences > 1 else ""
        blocks.append(
            '<div class="ai-entry"><div class="ai-entry-head">'
            f'<span class="ai-entry-status {css_class}">{escape(entry.status)}</span>'
            f'<span class="ai-entry-time">{escape(_short_time(entry.timestamp))}</span></div>'
            f'<p>{escape(entry.message)}</p>'
            f'<div class="ai-entry-meta">input {entry.is_fall} → result {result} · '
            f'{escape(entry.model)} · {escape(latency)}{escape(repeat)}</div></div>'
        )
    st.markdown("".join(blocks), unsafe_allow_html=True)


def _show_sensor_stream(entries: list[SensorStreamEntry]) -> None:
    if not entries:
        st.info("等待雷达帧或系统事件。")
        return
    lines = []
    for entry in reversed(entries[-18:]):
        raw = f" | raw={entry.raw}" if entry.raw else ""
        lines.append(
            '<div class="sensor-line">'
            f'{escape(_short_time(entry.timestamp))} <b>[{escape(entry.category)}]</b> '
            f'{escape(entry.text + raw)}</div>'
        )
    st.markdown(f'<div class="sensor-lines">{"".join(lines)}</div>', unsafe_allow_html=True)


@st.fragment(run_every=LOG_REFRESH_SECONDS)
def _show_logs(frame_path: Path, event_path: Path) -> None:
    """Refresh large log tables independently to avoid full-page flashing."""

    with st.container(key="log-dashboard"):
        frame_data = _read_csv(frame_path)
        if frame_data is None or frame_data.empty:
            return
        event_data = _read_csv(event_path, missing_ok=True)
        if event_data is None:
            event_data = pd.DataFrame()
        frame_data = _ensure_monitor_columns(frame_data)
        st.markdown(
            '<div class="subsection-heading"><h2>检测记录与原始数据</h2>'
            f'<span>最近 50 条 · 每 {LOG_REFRESH_SECONDS:g} 秒刷新</span></div>',
            unsafe_allow_html=True,
        )
        frame_tab, event_tab, raw_tab = st.tabs(["雷达帧", "系统事件", "原始数据"])
        with frame_tab:
            _show_frame_log(frame_data)
        with event_tab:
            _show_event_log(event_data)
        with raw_tab:
            latest = frame_data.iloc[-1]
            st.caption("最新原始串口帧 / mock 标识")
            st.code(_text(latest.get("raw")) or "当前帧没有原始数据", language=None, wrap_lines=True)
            st.caption("最新结构化点云")
            st.code(
                _text(latest.get("radar_points")) or "[]",
                language="json",
                wrap_lines=True,
            )


def _show_frame_log(data: pd.DataFrame) -> None:
    display = data.tail(50).iloc[::-1].rename(
        columns={
            "timestamp": "时间",
            "source": "数据来源",
            "human_present": "人体存在",
            "fall_detected": "雷达跌倒信号",
            "motion_state": "运动状态",
            "system_state": "Python 状态机",
            "device_state": "设备状态",
            "point_count": "点云数",
            "raw": "原始数据",
            "radar_is_fall": "雷达结果",
            "ai_result": "AI 结果",
            "ai_work_state": "AI 工作状态",
            "ai_trigger": "AI 触发原因",
            "ai_status": "AI 通道状态",
            "ai_model": "AI 模型",
            "ai_inference_ms": "推理耗时(ms)",
            "ai_message": "AI 响应",
            "final_result": "最终结果",
        }
    ).fillna("")
    st.dataframe(display, width="stretch", height=430, hide_index=True)


def _show_event_log(events: pd.DataFrame) -> None:
    if events.empty:
        st.info("还没有 AI、报警或设备连接事件。")
        return
    display = events.tail(50).iloc[::-1].rename(
        columns={
            "timestamp": "时间",
            "event": "事件",
            "state": "设备状态",
            "source": "数据来源",
            "details": "事件数据",
            "raw": "原始数据",
        }
    ).fillna("")
    st.dataframe(display, width="stretch", height=430, hide_index=True)


def _read_csv(path: Path, *, missing_ok: bool = False) -> pd.DataFrame | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return pd.DataFrame() if missing_ok else None
    except OSError as exc:
        st.error(f"读取 {path.name} 失败：{exc}")
        return None
    try:
        return _read_csv_snapshot(
            str(path),
            stat.st_mtime_ns,
            stat.st_size,
            DASHBOARD_MAX_ROWS,
        ).copy()
    except (CSVSnapshotError, OSError, UnicodeError) as exc:
        st.error(f"读取 {path.name} 失败：{exc}")
        return None


@st.cache_data(show_spinner=False, max_entries=16)
def _read_csv_snapshot(
    path: str,
    modified_ns: int,
    size: int,
    max_rows: int,
) -> pd.DataFrame:
    """Share one bounded file snapshot between independently timed fragments."""

    del modified_ns, size  # Values form the cache key; the reader takes its own snapshot.
    return pd.DataFrame.from_records(read_csv_tail(path, max_rows=max_rows))


def _ensure_monitor_columns(data: pd.DataFrame) -> pd.DataFrame:
    normalized = data.copy()
    fall = normalized.get("fall_detected", pd.Series(False, index=data.index))
    defaults: dict[str, object] = {
        "source": "unknown",
        "raw": "",
        "radar_is_fall": fall.map(lambda value: int(_as_bool(value))),
        "ai_result": fall.map(lambda value: int(_as_bool(value))),
        "final_result": fall.map(lambda value: int(_as_bool(value))),
        "ai_status": "AI_LEGACY",
        "ai_model": "legacy",
        "ai_inference_ms": 0.0,
        "ai_cached": False,
        "ai_message": "历史日志，未经过 AI 判断。",
        "device_state": "DISCONNECTED",
        "ai_work_state": "IDLE",
        "ai_trigger": "legacy",
        "point_count": 0,
        "radar_points": "[]",
    }
    for column, default in defaults.items():
        if column not in normalized.columns:
            normalized[column] = default
    return normalized


def _axis_domain(values: pd.Series, field: str) -> tuple[float, float]:
    baselines = {
        "x": (-1.8, 1.8),
        "y": (-0.2, 3.0),
        "z": (-0.4, 2.4),
    }
    baseline = baselines[field]
    return (
        min(baseline[0], float(values.min()) - 0.15),
        max(baseline[1], float(values.max()) + 0.15),
    )


def _trend_domain(values: pd.Series) -> tuple[float, float]:
    """Keep the XYZ timeline scale stable while still admitting outliers."""

    return (
        min(-1.8, float(values.min()) - 0.15),
        max(3.0, float(values.max()) + 0.15),
    )


def _install_scroll_policy() -> None:
    """Start full reloads at the wall header; fragments keep scroll position."""

    st.html(
        """
        <script>
        const page = window.parent;
        page.history.scrollRestoration = "manual";
        let attempts = 0;
        const resetMainScroll = () => {
            const main = page.document.querySelector('[data-testid="stMain"]');
            if (main) {
                main.scrollTo({top: 0, left: 0, behavior: "instant"});
                return;
            }
            if (attempts++ < 100) page.setTimeout(resetMainScroll, 20);
        };
        resetMainScroll();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _status_class(value: str) -> str:
    if value in {"CONNECTED", "NORMAL", "TRACKING", "PRESENT"}:
        return "connected"
    if value in {"ANALYZING", "OBSERVING", "SUSPECTED_FALL", "FALLBACK", "STALE", "WAITING"}:
        return "warning"
    if value in {"CONFIRMED_FALL", "FALL_DETECTED", "ERROR"}:
        return "danger"
    return ""


def _result(value: object) -> str:
    return "FALL · 1" if _as_bool(value) else "NORMAL · 0"


def _inference(latest: pd.Series) -> str:
    if _as_bool(latest.get("ai_cached")):
        return "cached"
    try:
        return f"{float(latest.get('ai_inference_ms')):.1f} ms"
    except (TypeError, ValueError):
        return "--"


def _short_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%H:%M:%S")
    except ValueError:
        return value or "--:--:--"


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"true", "1", "yes"}


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


if __name__ == "__main__":
    main()
