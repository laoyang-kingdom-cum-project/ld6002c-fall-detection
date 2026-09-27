from __future__ import annotations

from dataclasses import asdict
import inspect
from pathlib import Path
import re
import tomllib

import pandas as pd

import dashboard.community_ui as community_ui
from dashboard.app import (
    COMMUNITY_REFRESH_SECONDS,
    DARK_PALETTE,
    LIGHT_PALETTE,
    _axis_trend_chart,
    _css_theme_variables,
    _palette_for,
    _projection_chart,
    _refresh_interval,
    _simulated_trace_entries,
    _simulated_trace_key,
)


def test_palette_selects_dark_only_for_dark_theme() -> None:
    assert _palette_for("dark") is DARK_PALETTE
    assert _palette_for("light") is LIGHT_PALETTE
    assert _palette_for(None) is LIGHT_PALETTE


def test_css_variables_follow_the_browser_color_scheme() -> None:
    variables = _css_theme_variables()

    assert (
        f"--canvas: light-dark({LIGHT_PALETTE.canvas}, {DARK_PALETTE.canvas});"
        in variables
    )
    assert (
        "--terminal-bg: light-dark("
        f"{LIGHT_PALETTE.terminal_background}, {DARK_PALETTE.terminal_background});"
        in variables
    )


def test_md3_tokens_share_the_palette_source_of_truth() -> None:
    variables = _css_theme_variables()

    assert (
        "--md3-surface-container-high: light-dark("
        f"{LIGHT_PALETTE.surface_container_high}, "
        f"{DARK_PALETTE.surface_container_high});"
        in variables
    )
    assert (
        "--md3-secondary-container: light-dark("
        f"{LIGHT_PALETTE.secondary_container}, "
        f"{DARK_PALETTE.secondary_container});"
        in variables
    )
    assert DARK_PALETTE.canvas == "#10141D"
    assert DARK_PALETTE.surface == "#171B24"
    assert DARK_PALETTE.surface_container == "#202630"
    assert DARK_PALETTE.primary_container == "#284777"
    assert DARK_PALETTE.tertiary_container == "#17504F"
    assert DARK_PALETTE.success_container == "#1C5130"
    assert DARK_PALETTE.warning_container == "#624000"
    assert DARK_PALETTE.error_container == "#7A2930"
    assert "#FFFFFF" not in asdict(DARK_PALETTE).values()


def test_streamlit_defaults_to_recording_friendly_dark_theme() -> None:
    config = tomllib.loads(Path(".streamlit/config.toml").read_text(encoding="utf-8"))

    assert config["theme"]["base"] == "dark"
    assert config["theme"]["backgroundColor"] == DARK_PALETTE.canvas
    assert config["theme"]["secondaryBackgroundColor"] == (
        DARK_PALETTE.surface_container_low
    )


def test_community_ui_contains_no_independent_hex_color_literals() -> None:
    source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert re.search(r"#[0-9A-Fa-f]{3,8}", source) is None


def test_community_refresh_defaults_to_half_second_and_honors_override(
    monkeypatch,
) -> None:
    assert COMMUNITY_REFRESH_SECONDS == 0.5
    assert COMMUNITY_REFRESH_SECONDS <= 0.75

    monkeypatch.setenv("COMMUNITY_REFRESH_SECONDS", "0.6")
    assert _refresh_interval("COMMUNITY_REFRESH_SECONDS", 0.5) == 0.6


def test_community_css_uses_semantic_tonal_classes_and_state_layers() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    for css_class in (
        "stat-neutral",
        "stat-tertiary",
        "stat-success",
        "stat-secondary",
        "stat-warning",
        "stat-error",
    ):
        assert css_class in app_source
        assert css_class in community_source
    for css_class in (
        "resident-summary-identity",
        "resident-summary-radar",
        "resident-summary-ai",
        "resident-summary-model",
        "resident-summary-channel",
    ):
        assert css_class in app_source
    for semantic in ('"identity"', '"radar"', '"ai"', '"model"', '"channel"'):
        assert semantic in community_source
    assert "--md3-state-hover: 8%" in app_source
    assert "--md3-state-pressed: 12%" in app_source
    assert "@media (prefers-reduced-motion: reduce)" in app_source
    assert 'div[class*="-selected-"] button' in app_source
    assert "box-shadow: none !important" in app_source
    assert "st-key-community-bottom-btn-1" in app_source
    assert "st-key-community-bottom-btn-2" in app_source
    assert "st-key-community-bottom-btn-3" in app_source


def test_community_material_roles_are_scoped_and_lavender_led() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert '.st-key-community-dashboard {' in app_source
    assert '.wall-header-community,' in app_source
    assert '--md3-primary: #C9BEFF;' in app_source
    assert '--md3-primary-container: #4D426F;' in app_source
    assert '--md3-secondary-container: #3D4867;' in app_source
    assert '--md3-tertiary-container: #22544F;' in app_source
    assert '<header class="wall-header wall-header-{escape(view)}">' in app_source
    assert DARK_PALETTE.primary_container == "#284777"
    assert "linear-gradient" not in app_source
    assert "radial-gradient" not in app_source
    assert "📶" not in community_source
    assert "📵" not in community_source


def test_demo_control_reuses_the_approved_community_material_roles() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert ".wall-header-control," in app_source
    assert ".st-key-community-demo-control {" in app_source
    assert "--md3-primary: #C9BEFF;" in app_source
    assert "--md3-primary-container: #4D426F;" in app_source
    assert "--md3-secondary-container: #3D4867;" in app_source
    assert "--md3-tertiary-container: #22544F;" in app_source
    assert "st-key-demo-runtime-health" in app_source
    assert "st-key-demo-scenario-controls" in app_source
    assert "st-key-demo-current-state" in app_source
    assert '[data-testid="stMainBlockContainer"]:has(.st-key-community-demo-control)' in app_source
    assert 'div[data-testid="stButtonGroup"]' in app_source
    assert 'button[role="radio"][aria-checked="true"]' in app_source
    assert 'key="demo-runtime-health"' in community_source
    assert 'key="demo-scenario-controls"' in community_source
    assert 'key="demo-current-state"' in community_source
    assert 'key="demo-configuration"' in community_source
    assert "demo-control-section-title" in community_source


def test_demo_control_actions_share_one_family_with_semantic_tonal_roles() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")
    control_css = app_source[
        app_source.index("/* Demo Control:") : app_source.index(
            "@media (prefers-reduced-motion: reduce)"
        )
    ]

    expected_roles = {
        "NORMAL": "--md3-success-container",
        "FALL": "--md3-error-container",
        "WARNING": "--md3-warning-container",
        "BEND": "--md3-tertiary-container",
        "OFFLINE": "--md3-surface-container-highest",
        "RECOVER": "--md3-success-container",
        "ACKNOWLEDGE": "--md3-primary-container",
    }
    for action, role in expected_roles.items():
        selector = f'st-key-demo-action-{action}'
        start = app_source.index(selector)
        declaration = app_source[start : start + 260]
        assert role in declaration
    assert "translateY" not in control_css
    assert "scale(" not in control_css
    assert "--health-accent" in control_css
    assert "demo-health-cell::before" in control_css


def test_demo_control_keeps_simulated_and_real_ai_diagnostics_explicit() -> None:
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert "SIMULATED AI TRACE" in community_source
    assert "REAL AI" in community_source
    assert "判定来源" in community_source
    assert "demo-health-grid" in community_source
    assert "demo-health-banner warning" in community_source


def test_demo_control_exposes_bend_and_opt_in_status_voice_without_side_effects() -> None:
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert '"模拟弯腰", "BEND"' in community_source
    assert ':material/accessibility_new:' in community_source
    assert '"状态语音播报"' in community_source
    assert 'value=False' in community_source
    assert "voice_announcement_requested=voice_announcement_requested" in community_source
    assert "controller.request_demo_scenario" not in community_source
    assert "@st.fragment(run_every=0.5)" in community_source
    assert "def _render_demo_current_state(" in community_source


def test_dashboard_keeps_bend_out_of_fall_alarm_counts() -> None:
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")

    assert 'current_alerts = sum(state.status == "FALL"' in community_source
    assert 'event.get("event") == "FALL_ALERT"' in community_source
    assert 'st_val in {"FALL", "WARNING"} or state.posture_event == "BEND"' in community_source
    assert 'and state.posture_event == "NONE"' in community_source


def test_community_dashboard_uses_business_language_for_bend_and_source() -> None:
    dashboard_source = "\n".join(
        inspect.getsource(item)
        for item in (
            community_ui.render_community_dashboard,
            community_ui._render_resident_matrix,
            community_ui._render_operation_buttons,
            community_ui._render_selected_resident,
            community_ui._render_resident_status_capsule,
            community_ui._render_resident_summary,
        )
    )

    for diagnostic_text in (
        "课堂模拟",
        "弯腰姿态 · 演示",
        "BEND · 模拟",
        "DEMO_DIRECT",
        "DEMO_ONLY",
        "SIMULATED RADAR DATA · CLASSROOM DEMO",
    ):
        assert diagnostic_text not in dashboard_source
    assert "检测到弯腰姿态，当前安全状态正常。" in dashboard_source
    assert 'badge_text = "● 检测到弯腰姿态"' in dashboard_source
    assert 'posture = "弯腰"' in dashboard_source
    assert community_ui.EVENT_LABELS["BEND_SIMULATED"] == "弯腰姿态"
    assert community_ui._business_channel("DEMO_DIRECT") == "社区安全监护"
    assert community_ui._business_channel("LD6002C:serial") == (
        "LD6002C 毫米波雷达"
    )


def test_demo_and_technical_views_keep_simulation_diagnostics() -> None:
    community_source = Path("dashboard/community_ui.py").read_text(encoding="utf-8")
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")

    assert "判定来源 · {escape(state.source)}" in community_source
    assert "DEMO ONLY" in community_source
    assert "SIMULATED AI TRACE" in community_source
    assert "SIMULATED RADAR DATA · CLASSROOM DEMO" in app_source
    assert community_ui._voice_health_label("READY") == "Windows 中文语音可用"
    assert community_ui._voice_health_label("CONSOLE") == (
        "未检测到可用中文语音，仅控制台输出"
    )


def test_projection_chart_uses_dark_chart_colors() -> None:
    points = pd.DataFrame(
        [
            {
                "timestamp": "2026-08-18T12:00:00+08:00",
                "cluster_id": 1,
                "x": 0.1,
                "y": 1.2,
                "z": 0.4,
                "speed": 0.0,
                "is_latest_cloud": True,
            }
        ]
    )

    spec = _projection_chart(points, "x", "z", 100, DARK_PALETTE).to_dict()

    assert spec["background"] == DARK_PALETTE.chart_background
    assert spec["config"]["axis"]["gridColor"] == DARK_PALETTE.chart_grid
    assert spec["config"]["axis"]["labelColor"] == DARK_PALETTE.chart_axis
    assert spec["encoding"]["color"]["condition"]["value"] == DARK_PALETTE.secondary
    assert spec["encoding"]["color"]["value"] == DARK_PALETTE.tertiary


def test_axis_chart_uses_three_dark_mode_accent_colors() -> None:
    lines = pd.DataFrame(
        [
            {
                "time": "2026-08-18T12:00:00+08:00",
                "timestamp": "2026-08-18T12:00:00+08:00",
                "axis": "X",
                "position": 0.1,
                "point_count": 1,
                "mean_speed": 0.0,
            }
        ]
    )

    spec = _axis_trend_chart(lines, DARK_PALETTE).to_dict()

    assert spec["encoding"]["color"]["scale"]["range"] == [
        DARK_PALETTE.secondary,
        DARK_PALETTE.tertiary,
        DARK_PALETTE.on_secondary_container,
    ]
    assert spec["config"]["legend"]["labelColor"] == DARK_PALETTE.ink


def test_technical_detail_reuses_scoped_material_roles_without_new_chrome() -> None:
    app_source = Path("dashboard/app.py").read_text(encoding="utf-8")

    assert ".wall-header-technical," in app_source
    assert ".st-key-technical-page {" in app_source
    assert ".st-key-technical-page .monitor-status-item::before" in app_source
    assert ".st-key-technical-page .detail-row:nth-child(even)" in app_source
    assert ".st-key-technical-page .ai-entry:has(.ai-entry-status.simulated)" in app_source
    assert ".st-key-technical-page .sensor-line .sensor-category-radar" in app_source
    assert '.st-key-technical-page .st-key-log-dashboard [role="tablist"]' in app_source
    assert '.st-key-technical-page .st-key-log-dashboard [data-testid="stTab"]' in app_source
    assert '.st-key-technical-page [data-testid="stCode"]' in app_source
    assert 'f\'<span class="technical-appbar-chip">\u6570\u636e\u6e90 \u00b7' in app_source
    assert "\u26a1" not in app_source
    assert 'f\'<div class="monitor-status-item monitor-status-{semantic} {status_cls}">' in app_source


def test_resident_plotly_chart_uses_md3_theme_tokens() -> None:
    from dashboard.community_ui import _render_resident_height_chart
    from ld6002c_fall.community import ResidentState
    from unittest.mock import patch

    rendered = []
    state = ResidentState(
        resident_id="B1-101",
        status="FALL",
        radar_result=1,
        ai_result=1,
        source="DEMO_DIRECT",
    )
    with (
        patch("dashboard.community_ui.st.markdown"),
        patch(
            "dashboard.community_ui.st.plotly_chart",
            side_effect=lambda figure, **_: rendered.append(figure),
        ),
    ):
        _render_resident_height_chart(state, asdict(DARK_PALETTE))

    figure = rendered[0]
    assert figure.layout.paper_bgcolor == DARK_PALETTE.surface_container_high
    assert figure.layout.plot_bgcolor == DARK_PALETTE.surface_container_high
    assert figure.layout.xaxis.gridcolor == DARK_PALETTE.chart_grid
    assert figure.layout.hoverlabel.bgcolor == DARK_PALETTE.surface_container_highest
    assert figure.data[0].line.color == DARK_PALETTE.secondary
    assert figure.data[0].fillcolor == "rgba(208, 188, 255, 0.14)"
    assert figure.layout.shapes[0].line.color == DARK_PALETTE.danger


def test_bend_height_trend_stays_between_normal_and_fall() -> None:
    from dashboard.community_ui import _render_resident_height_chart
    from ld6002c_fall.community import ResidentState
    from unittest.mock import patch

    def rendered_heights(state: ResidentState) -> list[float]:
        figures = []
        with (
            patch("dashboard.community_ui.st.markdown"),
            patch(
                "dashboard.community_ui.st.plotly_chart",
                side_effect=lambda figure, **_: figures.append(figure),
            ),
        ):
            _render_resident_height_chart(state, asdict(DARK_PALETTE))
        return list(figures[0].data[0].y)

    normal = rendered_heights(ResidentState(resident_id="normal"))
    bend = rendered_heights(
        ResidentState(resident_id="bend", posture_event="BEND")
    )
    fall = rendered_heights(
        ResidentState(resident_id="fall", status="FALL", radar_result=1, ai_result=1)
    )

    assert min(fall) < min(bend) < min(normal)
    assert 0.8 <= min(bend) <= 1.0


def test_show_ai_timeline_renders_html() -> None:
    from ld6002c_fall.live_monitor import AIChatEntry
    from dashboard.app import _show_ai_timeline
    from unittest.mock import patch

    entries = [
        AIChatEntry(
            timestamp="2026-09-22T08:00:00+08:00",
            is_fall=1,
            result=1,
            status="FALL_DETECTED",
            model="qwen3:0.6b",
            message="检测到疑似跌倒事件",
            trigger="PERIODIC",
            occurrences=2,
            inference_ms=12.5,
        ),
        AIChatEntry(
            timestamp="2026-09-22T08:00:01+08:00",
            is_fall=0,
            result=0,
            status="FALLBACK",
            model="",
            message="规则引擎判定",
            trigger="PERIODIC",
            occurrences=1,
            inference_ms=None,
        ),
    ]

    rendered: list[str] = []
    with patch("dashboard.app.st.markdown", side_effect=lambda html, **_: rendered.append(html)):
        _show_ai_timeline(entries)

    assert len(rendered) == 1
    assert "merged 2" in rendered[0]
    assert "ai-entry-code" in rendered[0]
    assert "input 1 → 1" in rendered[0]
    assert "input 0 → 0" in rendered[0]
    assert '<span class="ai-entry-status warning">' in rendered[0]


def test_show_ai_timeline_labels_direct_trace_as_simulated() -> None:
    from ld6002c_fall.live_monitor import AIChatEntry
    from dashboard.app import _show_ai_timeline
    from unittest.mock import patch

    entries = [
        AIChatEntry(
            timestamp="2026-09-22T08:00:00.350+08:00",
            is_fall=1,
            result=1,
            status="FALL_CONFIRMED",
            model="qwen3:0.6b",
            message="跌倒报警",
            trigger="demo_direct",
            simulated=True,
            simulated_elapsed_ms=350,
        )
    ]

    rendered: list[str] = []
    with patch("dashboard.app.st.markdown", side_effect=lambda html, **_: rendered.append(html)):
        _show_ai_timeline(entries)

    assert "DEMO 1 → 1" in rendered[0]
    assert "分析耗时（演示） 350 ms" in rendered[0]
    assert "qwen3:0.6b" in rendered[0]
    assert "AI_RESPONSE" not in rendered[0]
    assert "08:00:00.350" in rendered[0]


def test_direct_trace_is_presented_in_order_with_non_blocking_css_delays() -> None:
    from ld6002c_fall.live_monitor import AIChatEntry
    from dashboard.app import _show_ai_timeline
    from unittest.mock import patch

    statuses = [
        "RADAR_INPUT",
        "FEATURE_EXTRACTED",
        "AI_REQUEST_SIMULATED",
        "AI_RESULT_SIMULATED",
        "FUSION_RESULT",
        "FALL_CONFIRMED",
    ]
    entries = [
        AIChatEntry(
            timestamp=f"2026-09-22T08:00:00.{index * 70:03d}+08:00",
            is_fall=1,
            result=1,
            status=status,
            model="qwen3:0.6b",
            message=status,
            trigger="demo_direct",
            simulated=True,
            simulated_elapsed_ms=350 if index == 5 else None,
        )
        for index, status in enumerate(statuses)
    ]

    assert [entry.status for entry in _simulated_trace_entries(entries)] == statuses
    assert _simulated_trace_key(entries) is not None

    rendered: list[str] = []
    with patch(
        "dashboard.app.st.markdown",
        side_effect=lambda html, **_: rendered.append(html),
    ):
        _show_ai_timeline(entries, animate_simulated=True)

    html = rendered[0]
    assert html.index("毫米波数据接收") < html.index("跌倒报警")
    for index in range(6):
        assert f"trace-sequenced trace-step-{index}" in html
    assert "AI_RESPONSE" not in html


def test_real_ai_timeline_never_uses_simulated_trace_animation() -> None:
    from ld6002c_fall.live_monitor import AIChatEntry
    from dashboard.app import _show_ai_timeline
    from unittest.mock import patch

    entries = [
        AIChatEntry(
            timestamp="2026-09-22T08:00:01+08:00",
            is_fall=1,
            result=1,
            status="FALL_DETECTED",
            model="qwen3:0.6b",
            message="real response",
            trigger="scenario_transition",
            inference_ms=120.0,
        )
    ]
    rendered: list[str] = []
    with patch(
        "dashboard.app.st.markdown",
        side_effect=lambda html, **_: rendered.append(html),
    ):
        _show_ai_timeline(entries, animate_simulated=True)

    assert "trace-sequenced" not in rendered[0]
    assert "SIMULATED AI TRACE" not in rendered[0]
