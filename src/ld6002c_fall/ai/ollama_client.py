"""Small, dependency-free Ollama client with strict validation and fallback."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AILabel, FallAIRequest, FallAIResult, OllamaHealth
from .prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_user_prompt

JsonTransport = Callable[[str, dict[str, Any] | None, float], dict[str, Any]]


class OllamaFallAI:
    """Map LD6002C is_fall through a local Ollama model.

    Identical sensor values reuse the last validated result. The real model is
    called on the first observation, on 0/1 transitions, or when ``force`` is
    requested. This keeps the serial loop responsive and the classroom log
    readable while every frame still passes through this bridge.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:0.6b",
        timeout: float = 10.0,
        transport: JsonTransport | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._transport = transport or _request_json
        self._cached_input: int | None = None
        self._cached_result: FallAIResult | None = None

    def health_check(self) -> OllamaHealth:
        """Check whether Ollama responds and the configured model exists."""

        try:
            payload = self._transport(f"{self.base_url}/api/tags", None, self.timeout)
            models = payload.get("models", [])
            names = {
                str(item.get("name", ""))
                for item in models
                if isinstance(item, dict)
            }
            if self.model not in names:
                return OllamaHealth(
                    connected=True,
                    model_available=False,
                    message=f"模型 {self.model} 未安装",
                )
            return OllamaHealth(True, True, "Ollama 与模型均可用")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
            return OllamaHealth(False, False, f"Ollama 不可用：{exc}")

    def predict(self, request: FallAIRequest, *, force: bool = False) -> FallAIResult:
        """Return a validated model result, or safely mirror the radar input."""

        if (
            not force
            and self._cached_input == request.is_fall
            and self._cached_result is not None
        ):
            return replace(self._cached_result, inference_ms=0.0, cached=True)

        started_at = perf_counter()
        try:
            response = self._transport(
                f"{self.base_url}/api/chat",
                self._build_payload(request),
                self.timeout,
            )
            result = self._parse_response(response, request.is_fall, started_at)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            result = self._fallback(request.is_fall, started_at, str(exc))

        self._cached_input = request.is_fall
        self._cached_result = result
        return result

    def _build_payload(self, request: FallAIRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": RESPONSE_SCHEMA,
            "options": {"temperature": 0, "num_predict": 80},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request.is_fall)},
            ],
        }

    def _parse_response(
        self,
        response: dict[str, Any],
        expected_result: int,
        started_at: float,
    ) -> FallAIResult:
        message = response["message"]
        if not isinstance(message, dict):
            raise TypeError("Ollama message must be an object")
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError("Ollama message content must be text")

        parsed = _parse_json_object(content)
        result = parsed.get("result")
        label = parsed.get("label")
        if type(result) is not int or result not in (0, 1):
            raise ValueError("AI result must be integer 0 or 1")
        if result != expected_result:
            raise ValueError("AI result does not match radar is_fall")

        expected_label: AILabel = "FALL" if result else "NORMAL"
        if label != expected_label:
            raise ValueError("AI label does not match result")

        response_message = parsed.get("message")
        if response_message is None:
            response_message = _default_message(result)
        if not isinstance(response_message, str) or not response_message.strip():
            raise ValueError("AI message must be non-empty text")

        return FallAIResult(
            result=result,
            label=expected_label,
            message=response_message.strip(),
            model=str(response.get("model") or self.model),
            inference_ms=(perf_counter() - started_at) * 1000,
            success=True,
        )

    def _fallback(
        self,
        is_fall: int,
        started_at: float,
        reason: str,
    ) -> FallAIResult:
        label: AILabel = "FALL" if is_fall else "NORMAL"
        detail = reason.strip() or "未知错误"
        return FallAIResult(
            result=is_fall,
            label=label,
            message=f"AI 服务不可用，使用雷达原始结果作为安全回退。原因：{detail}",
            model="fallback",
            inference_ms=(perf_counter() - started_at) * 1000,
            success=False,
        )


def disabled_ai_result(is_fall: int) -> FallAIResult:
    """Build an explicit pass-through result when AI is disabled by the CLI."""

    label: AILabel = "FALL" if is_fall else "NORMAL"
    return FallAIResult(
        result=is_fall,
        label=label,
        message="AI 判断已禁用，系统直接使用雷达原始结果。",
        model="disabled",
        inference_ms=0.0,
        success=False,
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise TypeError("AI response must be a JSON object")
    return parsed


def _default_message(result: int) -> str:
    if result:
        return "毫米波雷达检测到跌倒状态。"
    return "毫米波雷达当前未检测到跌倒。"


def _request_json(
    url: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urlopen(request, timeout=timeout) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise TypeError("Ollama API response must be a JSON object")
    return decoded
