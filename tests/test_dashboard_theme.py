from __future__ import annotations

import pandas as pd

from dashboard.app import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    _axis_trend_chart,
    _css_theme_variables,
    _palette_for,
    _projection_chart,
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
    assert spec["encoding"]["color"]["condition"]["value"] == DARK_PALETTE.terra
    assert spec["encoding"]["color"]["value"] == DARK_PALETTE.sage


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
        DARK_PALETTE.terra,
        DARK_PALETTE.sage,
        DARK_PALETTE.axis_blue,
    ]
    assert spec["config"]["legend"]["labelColor"] == DARK_PALETTE.ink


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

