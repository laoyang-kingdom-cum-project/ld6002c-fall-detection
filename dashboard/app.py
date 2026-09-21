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
from ld6002c_fall.community import CommunityController, CommunityTelemetryStore
from ld6002c_fall.config import (
    DEFAULT_COMMUNITY_CONFIG_PATH,
    DEFAULT_COMMUNITY_EVENT_PATH,
    DEFAULT_COMMUNITY_STATE_PATH,
    DEFAULT_COMMUNITY_TELEMETRY_DIR,
    DEFAULT_REAL_TELEMETRY_STALE_SECONDS,
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
    canvas="#F0F2F5",
    surface="#FFFFFF",
    surface_soft="#FAFAFA",
    ink="#1F2937",
    muted="#4B5563",
    line="#E5E7EB",
    header_background="rgba(255, 255, 255, 0.98)",
    terra="#1677FF",
    sage="#10B981",
    amber="#F59E0B",
    danger="#EF4444",
    axis_blue="#0284C7",
    chart_background="#FFFFFF",
    chart_line="#E5E7EB",
    chart_axis="#6B7280",
    chart_grid="#F3F4F6",
    terminal_background="#0B132B",
    terminal_text="#E2E8F0",
    terminal_line="#1E293B",
    terminal_accent="#38BDF8",
)

DARK_PALETTE = ThemePalette(
    mode="dark",
    canvas="#0B132B",
    surface="#111C38",
    surface_soft="#172554",
    ink="#F8FAFC",
    muted="#94A3B8",
    line="#1E293B",
    header_background="rgba(11, 19, 43, 0.96)",
    terra="#38BDF8",
    sage="#10B981",
    amber="#F59E0B",
    danger="#EF4444",
    axis_blue="#60A5FA",
    chart_background="#111C38",
    chart_line="#1E293B",
    chart_axis="#94A3B8",
    chart_grid="#1E293B",
    terminal_background="#070D1E",
    terminal_text="#F1F5F9",
    terminal_line="#1E293B",
    terminal_accent="#38BDF8",
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
    with st.container(key="technical-back-btn"):
        if st.button("返回社区大屏", icon=":material/arrow_back:", type="primary"):
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
    *,
    now: datetime | None = None,
    real_stale_seconds: float = DEFAULT_REAL_TELEMETRY_STALE_SECONDS,
) -> tuple[Path, Path, str, bool]:
    """Select recent real telemetry, otherwise the classroom demo stream."""

    resident = controller.registry.get(resident_id)
    state = controller.states()[resident_id]
    use_demo = (
        state.demo_override
        or not resident.has_live_sensor
        or not _telemetry_is_fresh(
            LOG_PATH,
            now=now or datetime.now().astimezone(),
            stale_seconds=real_stale_seconds,
        )
    )
    if use_demo:
        return (
            telemetry.frame_path(resident_id),
            telemetry.event_path(resident_id),
            "SIMULATED RADAR DATA · CLASSROOM DEMO",
            True,
        )
    return LOG_PATH, EVENT_LOG_PATH, "HLK-LD6002C · REALTIME", False


def _telemetry_is_fresh(
    path: Path,
    *,
    now: datetime,
    stale_seconds: float,
) -> bool:
    if stale_seconds <= 0:
        raise ValueError("stale_seconds must be greater than 0")
    try:
        rows = read_csv_tail(path, max_rows=1)
        timestamp = datetime.fromisoformat(str(rows[-1]["timestamp"]))
    except (CSVSnapshotError, FileNotFoundError, OSError, KeyError, IndexError, ValueError):
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()
    return abs((now - timestamp).total_seconds()) <= stale_seconds


def _install_styles() -> None:
    theme_variables = _css_theme_variables()
    styles = (
        """
        <style>
        :root {
            /* THEME_VARIABLES */
            --md3-primary: #005FB0;
            --md3-surface: #FFFFFF;
            --md3-surface-container: #E9EFF6;
            --md3-surface-container-high: #DEE6F2;
            --md3-on-surface: #1A1C1E;
            --md3-error-container: #FFDAD6;
            --md3-on-error-container: #410002;
            --md3-error: #BA1A1A;
            --md3-success-container: #C4EED0;
            --md3-on-success-container: #00210E;
            --md3-stat-purple: #E8DDFF;
            --md3-stat-amber: #FFDCC2;
            --md3-stat-cyan: #CCE8E7;
            --md3-shadow-1: 0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.08);
            --md3-shadow-2: 0 4px 12px rgba(0, 0, 0, 0.06), 0 2px 4px rgba(0, 0, 0, 0.04);
            --md3-shadow-glow: 0 8px 24px rgba(0, 95, 176, 0.3);
        }
        header[data-testid="stHeader"], [data-testid="stToolbar"] {
            display: none !important;
            height: 0 !important;
        }
        #MainMenu, footer {
            visibility: hidden !important;
        }
        .main .block-container,
        [data-testid="stMainBlockContainer"] {
            padding-top: 2.2rem !important;
            padding-bottom: 2rem !important;
            padding-left: 2.5rem !important;
            padding-right: 2.5rem !important;
            max-width: 100% !important;
            overflow-anchor: none;
        }
        .stApp { background: #F8F9FE; color: var(--md3-on-surface); }
        [data-testid="stAppViewContainer"] { background: #F8F9FE; }
        [data-testid="stMain"] { overflow-anchor: none; }
        [data-testid="stStatusWidget"],
        [data-testid="stSpinner"] { display: none !important; }
        .st-key-live-dashboard [data-testid="stElementContainer"],
        .st-key-log-dashboard [data-testid="stElementContainer"] {
            opacity: 1 !important;
            transition: none !important;
        }
        h1, h2, h3, p, span, div { letter-spacing: 0; }
        h1 { color: var(--md3-on-surface); font-weight: 700; }
        .wall-header {
            align-items: flex-end;
            border-bottom: 1px solid rgba(0, 0, 0, 0.06);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.8rem;
            padding: 0.2rem 0 0.8rem;
        }
        .wall-header h1 {
            font-size: 1.85rem;
            line-height: 1.15;
            margin: 0.25rem 0 0;
            color: #1A1C1E;
        }
        .wall-kicker, .section-kicker {
            color: var(--md3-primary);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .wall-live {
            align-items: center;
            color: #44474E;
            display: flex;
            font-size: 0.76rem;
            font-weight: 700;
            gap: 0.45rem;
            justify-content: flex-end;
            white-space: nowrap;
            background: var(--md3-surface-container);
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
        }
        .wall-live span {
            background: #008744;
            border-radius: 50%;
            display: inline-block;
            height: 8px;
            width: 8px;
        }
        /* MD3 Top Metric Cards */
        .community-stats {
            display: grid;
            gap: 0.75rem;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            margin: 0.65rem 0 1rem;
        }
        .community-stat {
            background: var(--md3-surface-container);
            border: none;
            border-radius: 18px;
            padding: 0.85rem 1.1rem;
            box-shadow: var(--md3-shadow-1);
            transition: transform 0.2s cubic-bezier(0.2, 0, 0, 1), box-shadow 0.2s cubic-bezier(0.2, 0, 0, 1);
        }
        .community-stat:hover {
            transform: translateY(-2px);
            box-shadow: var(--md3-shadow-2);
        }
        .community-stat.stat-blue {
            background: var(--md3-surface-container);
            color: #1A1C1E;
        }
        .community-stat.stat-purple {
            background: var(--md3-stat-purple);
            color: #21005D;
        }
        .community-stat.stat-amber {
            background: var(--md3-stat-amber);
            color: #311100;
        }
        .community-stat.stat-cyan {
            background: var(--md3-stat-cyan);
            color: #002021;
        }
        .community-stat.stat-green {
            background: var(--md3-success-container);
            color: var(--md3-on-success-container);
        }
        .community-stat.stat-red {
            background: var(--md3-error-container);
            color: var(--md3-on-error-container);
        }
        .community-stat.stat-red strong { color: var(--md3-error); }
        .community-stat span {
            color: inherit;
            opacity: 0.85;
            display: block;
            font-size: 0.72rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .community-stat strong {
            display: block;
            font-size: 1.6rem;
            line-height: 1.1;
            font-weight: 800;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            color: inherit;
        }
        .section-heading {
            align-items: baseline;
            border-bottom: 1px solid rgba(0, 0, 0, 0.06);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.65rem;
            padding-bottom: 0.45rem;
        }
        .section-heading.compact { margin-top: 0.75rem; }
        .section-heading h2 { font-size: 1.05rem; font-weight: 700; margin: 0.08rem 0 0; color: #1A1C1E; }
        .section-heading span { color: #44474E; font-size: 0.72rem; font-weight: 500; }

        /* MD3 Resident Matrix Cards */
        div[class*="st-key-resident-card-"] { margin-bottom: 0.35rem; }
        div[class*="st-key-resident-card-"] button {
            background: var(--md3-surface-container) !important;
            border: 1.5px solid transparent !important;
            border-radius: 20px !important;
            color: #1A1C1E !important;
            min-height: 64px !important;
            padding: 0.55rem 0.75rem !important;
            text-align: left !important;
            box-shadow: var(--md3-shadow-1) !important;
            transition: all 0.2s cubic-bezier(0.2, 0, 0, 1) !important;
        }
        div[class*="st-key-resident-card-"] button:hover {
            background: var(--md3-surface-container-high) !important;
            box-shadow: var(--md3-shadow-2) !important;
            transform: translateY(-1.5px) !important;
        }
        div[class*="st-key-resident-card-"] button p {
            font-size: 0.73rem !important;
            line-height: 1.4 !important;
            white-space: pre-line !important;
            margin: 0 !important;
            color: inherit !important;
            font-weight: 600 !important;
        }
        div[class*="st-key-resident-card-warning"] button {
            background: #FFF4E5 !important;
            border-color: #FFB74D !important;
            color: #E65100 !important;
        }
        div[class*="st-key-resident-card-fall"] button {
            background: var(--md3-error-container) !important;
            border-color: var(--md3-error) !important;
            color: var(--md3-on-error-container) !important;
            animation: clinical-pulse 1.8s infinite cubic-bezier(0.4, 0, 0.6, 1) !important;
        }
        div[class*="st-key-resident-card-offline"] button {
            background: #ECEFF1 !important;
            color: #78909C !important;
            opacity: 0.85 !important;
        }
        /* Active Selected Card: MD3 High Saturation Royal Cobalt Blue */
        div[class*="-selected-"] button {
            background: var(--md3-primary) !important;
            border: 2px solid #004785 !important;
            color: #FFFFFF !important;
            box-shadow: var(--md3-shadow-glow) !important;
            transform: scale(1.02) !important;
        }
        div[class*="-selected-"] button:hover {
            background: #005096 !important;
            box-shadow: 0 10px 28px rgba(0, 95, 176, 0.4) !important;
            color: #FFFFFF !important;
        }
        div[class*="-selected-"] button p {
            color: #FFFFFF !important;
            font-weight: 700 !important;
        }

        /* Filter Segmented Control Pills */
        div[data-testid="stSegmentedControl"] {
            background: var(--md3-surface-container) !important;
            border-radius: 9999px !important;
            padding: 3px !important;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.06) !important;
        }
        div[data-testid="stSegmentedControl"] button {
            border-radius: 9999px !important;
            border: none !important;
            font-weight: 600 !important;
            font-size: 0.76rem !important;
            padding: 0.3rem 0.9rem !important;
            transition: all 0.2s cubic-bezier(0.2, 0, 0, 1) !important;
        }

        /* MD3 Right Detail Panel */
        .st-key-community-detail-panel {
            background: #FFFFFF !important;
            border: 1px solid rgba(0, 0, 0, 0.05) !important;
            border-radius: 24px !important;
            min-height: 480px !important;
            padding: 1.5rem !important;
            box-shadow: var(--md3-shadow-2) !important;
        }
        .st-key-community-detail-panel .panel-heading {
            margin-bottom: 0.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid rgba(0, 0, 0, 0.06);
        }
        .st-key-community-detail-panel .state-hero { padding: 0.4rem 0 0.65rem; }
        .st-key-community-detail-panel .state-value { font-size: 1.45rem; }
        .st-key-community-detail-panel .detail-row { min-height: 36px; border-bottom: 1px solid rgba(0, 0, 0, 0.05); }

        /* MD3 Large Filled Action Buttons */
        div[class*="st-key-community-bottom-btn-"] button,
        div[class*="st-key-community-ack-btn"] button,
        div[class*="st-key-community-rec-btn"] button,
        div[class*="st-key-community-tech-btn"] button {
            height: 44px !important;
            min-height: 44px !important;
            border-radius: 28px !important;
            font-weight: 700 !important;
            font-size: 0.82rem !important;
            border: none !important;
            letter-spacing: 0.02em !important;
            box-shadow: var(--md3-shadow-1) !important;
            transition: all 0.2s cubic-bezier(0.2, 0, 0, 1) !important;
        }
        div[class*="st-key-community-bottom-btn-"] button:hover,
        div[class*="st-key-community-ack-btn"] button:hover,
        div[class*="st-key-community-rec-btn"] button:hover,
        div[class*="st-key-community-tech-btn"] button:hover {
            transform: translateY(-2px) !important;
            box-shadow: var(--md3-shadow-2) !important;
        }
        div[class*="st-key-community-bottom-btn-1"] button {
            background: #E8DDFF !important;
            color: #21005D !important;
        }
        div[class*="st-key-community-bottom-btn-2"] button {
            background: #FFDCC2 !important;
            color: #311100 !important;
        }
        div[class*="st-key-community-bottom-btn-3"] button {
            background: #CCE8E7 !important;
            color: #002021 !important;
        }
        div[class*="st-key-community-ack-btn"] button {
            background: var(--md3-error) !important;
            color: #FFFFFF !important;
        }
        div[class*="st-key-community-rec-btn"] button {
            background: var(--md3-surface-container) !important;
            color: var(--md3-primary) !important;
        }
        div[class*="st-key-community-tech-btn"] button {
            background: var(--md3-primary) !important;
            color: #FFFFFF !important;
        }

        /* MD3 Return Button */
        div[class*="st-key-technical-back-btn"] button {
            border-radius: 9999px !important;
            background: var(--md3-primary) !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            font-size: 0.84rem !important;
            height: 42px !important;
            min-height: 42px !important;
            padding: 0 1.6rem !important;
            border: none !important;
            box-shadow: var(--md3-shadow-1) !important;
            margin-bottom: 0.6rem !important;
            display: inline-flex !important;
            align-items: center !important;
            gap: 0.4rem !important;
            transition: all 0.2s cubic-bezier(0.2, 0, 0, 1) !important;
        }
        div[class*="st-key-technical-back-btn"] button:hover {
            background: #005096 !important;
            box-shadow: var(--md3-shadow-2) !important;
            transform: translateY(-1px) !important;
            color: #FFFFFF !important;
        }

        .technical-resident-context {
            align-items: center;
            background: var(--md3-surface-container);
            border-left: 4px solid var(--md3-primary);
            border-radius: 12px;
            display: flex;
            justify-content: space-between;
            margin: 0.55rem 0 0.75rem;
            padding: 0.65rem 0.95rem;
        }
        .technical-resident-context strong { font-size: 0.9rem; }
        .technical-resident-context span { color: #44474E; font-size: 0.72rem; }
        .simulation-notice {
            background: #FFF4E5;
            border: 1px solid #FFE0B2;
            border-left: 4px solid #F59E0B;
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            margin-bottom: 0.75rem;
            padding: 0.75rem;
        }
        .simulation-notice span { color: #5D4037; font-size: 0.78rem; }
        .monitor-status-grid {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            margin: 0.7rem 0;
        }
        .monitor-status-item {
            background: #EBF1FA;
            border: none;
            border-radius: 18px;
            min-width: 0;
            padding: 0.75rem 0.95rem;
            box-shadow: var(--md3-shadow-1);
            transition: transform 0.2s cubic-bezier(0.2, 0, 0, 1), box-shadow 0.2s cubic-bezier(0.2, 0, 0, 1);
        }
        .monitor-status-item:hover {
            transform: translateY(-2px);
            box-shadow: var(--md3-shadow-2);
        }
        .monitor-status-item.connected { background: #EBF1FA; }
        .monitor-status-item.warning { background: #FFDCC2; }
        .monitor-status-item.danger { background: var(--md3-error-container); }
        .monitor-status-label {
            color: #44474E;
            display: block;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 0.28rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .monitor-status-value {
            color: #1A1C1E;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.2;
            overflow-wrap: anywhere;
        }
        .monitor-status-item.danger .monitor-status-value { color: var(--md3-on-error-container); }
        .monitor-status-item.warning .monitor-status-value { color: #311100; }
        .status-live-dot {
            width: 8px;
            height: 8px;
            background-color: #008744;
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 0 0 rgba(0, 135, 68, 0.7);
            animation: pulse-live 1.8s infinite;
        }
        @keyframes pulse-live {
            0% {
                transform: scale(0.95);
                box-shadow: 0 0 0 0 rgba(0, 135, 68, 0.7);
            }
            70% {
                transform: scale(1);
                box-shadow: 0 0 0 6px rgba(0, 135, 68, 0);
            }
            100% {
                transform: scale(0.95);
                box-shadow: 0 0 0 0 rgba(0, 135, 68, 0);
            }
        }
        .current-alert {
            align-items: center;
            background: #E8F8EE;
            border-radius: 16px;
            box-shadow: var(--md3-shadow-1);
            display: flex;
            font-size: 0.88rem;
            font-weight: 600;
            min-height: 44px;
            padding: 0.65rem 1.1rem;
            margin-bottom: 0.85rem;
            border: none;
            color: #00210E;
        }
        .current-alert.safe { background: #E8F8EE; color: #00210E; }
        .current-alert.warning { background: #FFF4E5; color: #663C00; }
        .current-alert.danger { background: var(--md3-error-container); color: var(--md3-on-error-container); }
        .st-key-overview-panel,
        .st-key-coordinate-panel,
        .st-key-ai-panel {
            background: #FFFFFF;
            border: 1px solid rgba(0, 0, 0, 0.05);
            border-radius: 24px;
            min-height: 550px;
            padding: 1.4rem;
            box-shadow: var(--md3-shadow-1);
        }
        .st-key-axis-trend-panel {
            background: #FFFFFF;
            border: 1px solid rgba(0, 0, 0, 0.05);
            border-radius: 24px;
            margin-top: 0.9rem;
            padding: 1.4rem;
            box-shadow: var(--md3-shadow-1);
        }
        .panel-heading {
            align-items: flex-start;
            border-bottom: 1px solid rgba(0, 0, 0, 0.06);
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.85rem;
            padding-bottom: 0.7rem;
        }
        .panel-heading h2 {
            font-size: 1.1rem;
            font-weight: 700;
            line-height: 1.2;
            margin: 0.16rem 0 0;
            color: #1A1C1E;
        }
        .panel-note { color: #44474E; font-size: 0.72rem; text-align: right; }
        .state-hero { padding: 0.6rem 0 0.9rem; }
        .state-label { color: #44474E; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
        .state-hero-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            border-radius: 9999px;
            padding: 0.65rem 1.2rem;
            font-size: 1.3rem;
            font-weight: 750;
            margin-top: 0.35rem;
            letter-spacing: 0.02em;
            box-shadow: var(--md3-shadow-1);
        }
        .state-hero-pill.safe, .state-hero-pill.connected { background: var(--md3-success-container); color: var(--md3-on-success-container); }
        .state-hero-pill.warning { background: #FFDCC2; color: #311100; }
        .state-hero-pill.danger { background: var(--md3-error); color: #FFFFFF; animation: clinical-pulse 1.8s infinite cubic-bezier(0.4, 0, 0.6, 1); }
        .detail-list { display: flex; flex-direction: column; gap: 0.35rem; }
        .detail-row {
            align-items: center;
            background: #F8F9FE;
            border-radius: 12px;
            display: flex;
            justify-content: space-between;
            min-height: 40px;
            padding: 0.45rem 0.85rem;
            border: none;
        }
        .detail-row span { color: #44474E; font-size: 0.76rem; font-weight: 500; }
        .detail-row strong { font-size: 0.86rem; color: #1A1C1E; font-weight: 700; overflow-wrap: anywhere; text-align: right; }
        .coordinate-stats-wrapper {
            background: #E9EFF6;
            border-radius: 16px;
            padding: 0.45rem 0.65rem;
            margin-bottom: 0.8rem;
        }
        .coordinate-stats, .ai-meta-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.4rem;
            border: none;
            margin-bottom: 0;
        }
        .coordinate-stat, .ai-meta-item {
            background: #FFFFFF;
            border-radius: 12px;
            border: none;
            min-width: 0;
            padding: 0.45rem 0.65rem;
            text-align: center;
            box-shadow: var(--md3-shadow-1);
        }
        .coordinate-stat:first-child, .ai-meta-item:first-child { padding-left: 0.65rem; }
        .coordinate-stat:last-child, .ai-meta-item:last-child { border-right: none; }
        .coordinate-stat span, .ai-meta-item span {
            color: #44474E;
            display: block;
            font-size: 0.64rem;
            font-weight: 600;
            margin-bottom: 0.15rem;
            text-transform: uppercase;
        }
        .coordinate-stat strong, .ai-meta-item strong {
            display: block;
            font-size: 0.86rem;
            font-weight: 750;
            color: #1A1C1E;
            overflow-wrap: anywhere;
        }
        .projection-label {
            color: #44474E;
            font-size: 0.68rem;
            font-weight: 700;
            margin: 0.2rem 0 0.1rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .axis-trend-stats-wrapper {
            background: #E9EFF6;
            border-radius: 16px;
            padding: 0.45rem 0.65rem;
            margin-bottom: 0.8rem;
        }
        .axis-trend-stats {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.4rem;
            border: none;
            margin-bottom: 0;
        }
        .axis-trend-stat {
            background: #FFFFFF;
            border-radius: 12px;
            border: none;
            min-width: 0;
            padding: 0.45rem 0.65rem;
            text-align: center;
            box-shadow: var(--md3-shadow-1);
        }
        .axis-trend-stat:first-child { padding-left: 0.65rem; }
        .axis-trend-stat:last-child { border-right: none; }
        .axis-trend-stat span {
            color: #44474E;
            display: block;
            font-size: 0.64rem;
            font-weight: 600;
            margin-bottom: 0.12rem;
            text-transform: uppercase;
        }
        .axis-trend-stat strong { display: block; font-size: 0.88rem; font-weight: 750; }
        .axis-trend-stat.x strong { color: var(--md3-primary); }
        .axis-trend-stat.y strong { color: #008744; }
        .axis-trend-stat.z strong { color: #0284C7; }
        .axis-trend-empty {
            align-items: center;
            background: #F8F9FE;
            border: 1px dashed rgba(0, 0, 0, 0.12);
            border-radius: 16px;
            color: #44474E;
            display: flex;
            justify-content: center;
            min-height: 220px;
        }
        [data-testid="stVegaLiteChart"] {
            background: transparent !important;
            border: none !important;
            border-radius: 12px;
        }
        details[title="Click to view actions"] { display: none; }
        .coordinate-empty {
            align-items: center;
            background: #F8F9FE;
            border: 1px dashed rgba(0, 0, 0, 0.12);
            border-radius: 16px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-height: 410px;
            text-align: center;
        }
        .coordinate-empty strong { font-size: 1rem; color: #1A1C1E; }
        .coordinate-empty span { color: #44474E; font-size: 0.76rem; margin-top: 0.35rem; }
        .ai-entry {
            background: #F0F4F9;
            border-radius: 14px;
            margin: 8px 0;
            padding: 10px 14px;
            border: none;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            transition: transform 0.15s ease;
        }
        .ai-entry:hover {
            transform: translateY(-1px);
        }
        .ai-entry-head { align-items: center; display: flex; justify-content: space-between; gap: 0.5rem; }
        .ai-entry-status {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            color: #008744;
            font-size: 0.72rem;
            font-weight: 750;
        }
        .ai-entry-status.danger { color: var(--md3-error); }
        .ai-entry-status.warning { color: #D97706; }
        .ai-entry-time { color: #74777F; font-size: 0.68rem; font-weight: 500; }
        .ai-entry p { font-size: 0.82rem; line-height: 1.45; margin: 0.35rem 0; color: #1A1C1E; }
        .ai-entry-meta { color: #74777F; font-size: 0.68rem; overflow-wrap: anywhere; }
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
        /* MD3 Metric Component Styling */
        div[data-testid="stMetric"] {
            background: var(--md3-surface-container) !important;
            border: none !important;
            border-radius: 18px !important;
            padding: 0.85rem 1.1rem !important;
            box-shadow: var(--md3-shadow-1) !important;
            transition: transform 0.2s cubic-bezier(0.2, 0, 0, 1), box-shadow 0.2s cubic-bezier(0.2, 0, 0, 1);
        }
        div[data-testid="stMetric"]:hover {
            transform: translateY(-2px);
            box-shadow: var(--md3-shadow-2) !important;
        }
        div[data-testid="stMetric"] label[data-testid="stMetricLabel"] {
            color: #44474E;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
            color: #1A1C1E;
            font-size: 1.5rem;
            font-weight: 800;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }
        .sensor-line { border-bottom: 1px solid var(--terminal-line); padding: 0.18rem 0; }
        .sensor-line:last-child { border-bottom: 0; }
        .sensor-line b { color: var(--terminal-accent); font-weight: 600; }
        [data-testid="stDataFrame"] {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03);
        }
        [data-baseweb="tab-list"] { gap: 0.2rem; }
        [data-baseweb="tab"] { letter-spacing: 0; font-weight: 600; }
        #vg-tooltip-element.vg-tooltip {
            background: var(--surface) !important;
            border-color: var(--line) !important;
            color: var(--ink) !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        @keyframes clinical-pulse {
            0% {
                background-color: #DC2626;
                box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.7);
            }
            50% {
                background-color: #EF4444;
                box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
            }
            100% {
                background-color: #DC2626;
                box-shadow: 0 0 0 0 rgba(220, 38, 38, 0);
            }
        }
        .current-alert.danger {
            background: var(--md3-error-container) !important;
            color: var(--md3-on-error-container) !important;
            border: 1.5px solid var(--md3-error) !important;
            border-radius: 16px !important;
            font-weight: 700 !important;
            animation: clinical-pulse 1.8s infinite cubic-bezier(0.4, 0, 0.6, 1);
            letter-spacing: 0.02em;
        }
        .current-alert.danger span,
        .current-alert.danger strong {
            color: var(--md3-on-error-container) !important;
        }
        .current-alert.safe,
        .current-alert:not(.warning):not(.danger) {
            background: #E8F8EE !important;
            color: #00210E !important;
            border: 1px solid #C4EED0 !important;
            border-radius: 16px !important;
            font-weight: 600 !important;
        }
        .current-alert.warning {
            background: #FFF4E5 !important;
            color: #663C00 !important;
            border: 1px solid #FFE0B2 !important;
            border-radius: 16px !important;
            font-weight: 600 !important;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.3rem 0.85rem;
            border-radius: 9999px;
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }
        .status-badge.safe {
            background: #C4EED0 !important;
            color: #00210E !important;
            border: none !important;
        }
        .status-badge.alarm {
            background: var(--md3-error) !important;
            color: #FFFFFF !important;
            border: none !important;
            animation: clinical-pulse 2s infinite;
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
        st.info("监测服务正在初始化，请稍候查看第一帧数据。")
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
        ("Intelligent Result", "FALL" if snapshot.fall_detected else "NORMAL"),
        ("Data Source", snapshot.source),
    ]
    cards = []
    for label, value in items:
        status_cls = _status_class(value)
        live_dot = '<span class="status-live-dot"></span>' if value in {"CONNECTED", "LIVE"} else ""
        cards.append(
            f'<div class="monitor-status-item {status_cls}">'
            f'<span class="monitor-status-label">{escape(label)}</span>'
            f'<strong class="monitor-status-value">{live_dot}{escape(value)}</strong>'
            '</div>'
        )
    st.markdown(f'<div class="monitor-status-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _show_current_alert(status: str) -> None:
    if status == "CONFIRMED_FALL":
        css_class = "danger"
        badge_html = '<span class="status-badge alarm">● 紧急警报 ALARM</span>'
        message = "【紧急跌倒报警】毫米波雷达与智能分析已确认跌倒事件，现场声光报警已触发！"
    elif status == "SUSPECTED_FALL":
        css_class = "warning"
        badge_html = '<span class="status-badge" style="background:#FEF3C7;color:#D97706;border:1px solid #FCD34D;">▲ 疑似跌倒</span>'
        message = "持续检测到人体异常姿态信号，系统进入防误报延时二次判定中..."
    elif status == "OBSERVING":
        css_class = "warning"
        badge_html = '<span class="status-badge" style="background:#EFF6FF;color:#0284C7;border:1px solid #BAE6FD;">ℹ 分析中</span>'
        message = "雷达检测到空间微动信号，系统正在持续观察并更新最新点云。"
    elif status == "DISCONNECTED":
        css_class = "warning"
        badge_html = '<span class="status-badge" style="background:#F1F5F9;color:#64748B;border:1px solid #CBD5E1;">✕ 链路断开</span>'
        message = "传感器串口或数据总线链路中断，正在等待主程序重连..."
    elif status == "NO_PERSON":
        css_class = "safe"
        badge_html = '<span class="status-badge safe">✓ 监护安全 · 无人</span>'
        message = "当前监测区域无人，毫米波生命体征链路保持静默待机与实时巡检。"
    else:
        css_class = "safe"
        badge_html = '<span class="status-badge safe">✓ 监护正常 · 有人</span>'
        message = "受监护人员体征与姿态稳定，连续雷达微动追踪中。"
    st.markdown(
        f'<div class="current-alert {css_class}">'
        f'{badge_html}&nbsp;&nbsp;<span>{escape(message)}</span>'
        f'</div>',
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
        f'<div class="state-hero-pill {state_class}">{escape(state_label)}</div></div>'
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
    st.markdown(f'<div class="coordinate-stats-wrapper"><div class="coordinate-stats">{stats_html}</div></div>', unsafe_allow_html=True)

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
    st.markdown(f'<div class="axis-trend-stats-wrapper"><div class="axis-trend-stats">{stats_html}</div></div>', unsafe_allow_html=True)

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
    decision_source = _business_ai_source(snapshot.ai_model)
    work_state = _business_ai_state(snapshot.ai_work_state)
    st.markdown(
        '<div class="panel-heading"><div><div class="section-kicker">Local Intelligence</div>'
        '<h2>AI 判断流</h2></div>'
        f'<span class="panel-note">{escape(decision_source)}<br>{escape(work_state)}</span></div>',
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
    st.markdown(f'<div class="coordinate-stats-wrapper"><div class="ai-meta-grid">{meta_html}</div></div>', unsafe_allow_html=True)
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
        dot_color = "#008744"
        if entry.status in {"FALL_DETECTED", "ALARM_TRIGGERED"}:
            css_class = "danger"
            dot_color = "#BA1A1A"
        elif entry.status == "ANALYZING":
            css_class = "warning"
            dot_color = "#D97706"
        status = "规则判定完成" if entry.status == "FALLBACK" else entry.status
        message = (
            "本地安全规则已完成判定。"
            if entry.status == "FALLBACK"
            else entry.message
        )
        model = "本地安全规则" if entry.status == "FALLBACK" else entry.model
        result = "--" if entry.result is None else str(entry.result)
        latency = (
            f"{entry.inference_ms:.1f} ms" if entry.inference_ms is not None else "waiting"
        )
        repeat = f" · merged {entry.occurrences}" if entry.occurrences > 1 else ""
        dot_html = f'<span style="width:7px;height:7px;border-radius:50%;background:{dot_color};display:inline-block;margin-right:5px;"></span>'
        blocks.append(
            '<div class="ai-entry"><div class="ai-entry-head">'
            f'<span class="ai-entry-status {css_class}">{dot_html}{escape(status)}</span>'
            f'<span class="ai-entry-time">{escape(_short_time(entry.timestamp))}</span></div>'
            f'<p>{escape(message)}</p>'
            f'<div class="ai-entry-meta">input {entry.is_fall} → result {result} · '
            f'{escape(model)} · {escape(latency)}{escape(repeat)}</div></div>'
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


def _business_ai_source(model: str) -> str:
    return "本地安全规则" if model in {"fallback", "disabled", "not-requested"} else model


def _business_ai_state(work_state: str) -> str:
    return {
        "FALLBACK": "判定完成",
        "ERROR": "判定完成",
        "MONITORING": "持续监测",
        "FALL_DETECTED": "跌倒已确认",
        "IDLE": "持续监测",
    }.get(work_state, work_state)


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
