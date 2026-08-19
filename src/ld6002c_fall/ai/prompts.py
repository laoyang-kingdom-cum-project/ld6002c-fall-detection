"""Fixed prompt and JSON schema for deterministic fall-state mapping."""

from __future__ import annotations

SYSTEM_PROMPT = """你是一个毫米波雷达老人跌倒检测 AI 判断模块。

你只会收到 HLK-LD6002C 毫米波雷达提供的 is_fall 数据。

规则：
- is_fall = 0 表示正常，必须返回 result=0、label=NORMAL。
- is_fall = 1 表示跌倒，必须返回 result=1、label=FALL。
- 必须严格按照输入返回判断，不允许改变传感器语义。
- result 必须是整数 0 或 1。
- message 使用一句简短中文说明。
- 只返回要求的 JSON 结构，不要返回 Markdown 或解释文字。
"""

RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "result": {"type": "integer", "enum": [0, 1]},
        "label": {"type": "string", "enum": ["NORMAL", "FALL"]},
        "message": {"type": "string"},
    },
    "required": ["result", "label", "message"],
}


def build_user_prompt(is_fall: int) -> str:
    """Build the intentionally minimal sensor message."""

    return f"is_fall = {is_fall}"
