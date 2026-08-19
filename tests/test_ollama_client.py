from __future__ import annotations

from typing import Any

import pytest

from ld6002c_fall.ai.models import FallAIRequest
from ld6002c_fall.ai.ollama_client import OllamaFallAI


def response(content: str) -> dict[str, Any]:
    return {"model": "qwen3:0.6b", "message": {"content": content}}


@pytest.mark.parametrize(
    ("is_fall", "content", "expected_label"),
    [
        (0, '{"result":0,"label":"NORMAL"}', "NORMAL"),
        (1, '{"result":1,"label":"FALL"}', "FALL"),
    ],
)
def test_predict_parses_valid_result(
    is_fall: int,
    content: str,
    expected_label: str,
) -> None:
    client = OllamaFallAI(transport=lambda *_: response(content))

    result = client.predict(FallAIRequest(is_fall))

    assert result.result == is_fall
    assert result.label == expected_label
    assert result.success is True
    assert result.model == "qwen3:0.6b"


def test_predict_accepts_json_surrounded_by_extra_text() -> None:
    client = OllamaFallAI(
        transport=lambda *_: response(
            'result follows: {"result":1,"label":"FALL","message":"检测到跌倒"} done'
        )
    )

    result = client.predict(FallAIRequest(1))

    assert result.success is True
    assert result.result == 1


def test_invalid_json_uses_radar_fallback() -> None:
    client = OllamaFallAI(transport=lambda *_: response("not json"))

    result = client.predict(FallAIRequest(1))

    assert result.success is False
    assert result.result == 1
    assert result.label == "FALL"
    assert result.model == "fallback"


def test_timeout_uses_radar_fallback() -> None:
    def timeout_transport(*_: object) -> dict[str, Any]:
        raise TimeoutError("timed out")

    client = OllamaFallAI(transport=timeout_transport)

    result = client.predict(FallAIRequest(0))

    assert result.success is False
    assert result.result == 0
    assert "安全回退" in result.message


def test_invalid_result_uses_radar_fallback() -> None:
    client = OllamaFallAI(
        transport=lambda *_: response('{"result":5,"label":"FALL"}')
    )

    result = client.predict(FallAIRequest(0))

    assert result.success is False
    assert result.result == 0


def test_mismatched_label_uses_radar_fallback() -> None:
    client = OllamaFallAI(
        transport=lambda *_: response('{"result":1,"label":"NORMAL"}')
    )

    result = client.predict(FallAIRequest(1))

    assert result.success is False
    assert result.result == 1


def test_result_that_changes_radar_semantics_uses_fallback() -> None:
    client = OllamaFallAI(
        transport=lambda *_: response('{"result":0,"label":"NORMAL"}')
    )

    result = client.predict(FallAIRequest(1))

    assert result.success is False
    assert result.result == 1


def test_identical_input_uses_cached_result() -> None:
    call_count = 0

    def transport(*_: object) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return response('{"result":0,"label":"NORMAL"}')

    client = OllamaFallAI(transport=transport)

    first = client.predict(FallAIRequest(0))
    second = client.predict(FallAIRequest(0))

    assert first.cached is False
    assert second.cached is True
    assert second.inference_ms == 0.0
    assert call_count == 1
