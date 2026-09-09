"""OpenAI 兼容协议实现。

智谱 GLM、DeepSeek、通义、OpenAI 都提供 OpenAI 兼容端点，
所以一个实现就能通吃多家，切换模型只需要改 base_url / model / api_key。
"""

from __future__ import annotations

import json
import os

from ..types import LLMResponse, Message, ToolCall, Usage
from .base import ModelProvider, ProviderError

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class OpenAICompatProvider(ModelProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        self.temperature = temperature
        self.timeout = timeout

        resolved_key = api_key or os.getenv(api_key_env)
        if not resolved_key:
            raise ProviderError(
                f"未提供 API Key：请传 api_key 参数，或设置环境变量 {api_key_env}"
            )

        # 延迟导入，保证不装 openai 也能跑核心逻辑的测试
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("未安装 openai 包，请先 pip install openai") from exc

        self.name = f"openai-compat:{model}"
        self._client = OpenAI(api_key=resolved_key, base_url=self.base_url, timeout=timeout)

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": [m.to_payload() for m in messages],
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            response = self._client.chat.completions.create(**payload)
        except Exception as exc:  # 各家 SDK 异常类型不统一，统一包一层
            raise ProviderError(f"模型调用失败：{exc}") from exc

        choice = response.choices[0]
        raw = choice.message
        tool_calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=_parse_arguments(call))
            for call in (raw.tool_calls or [])
        ]

        usage = getattr(response, "usage", None)
        return LLMResponse(
            message=Message(role="assistant", content=raw.content or "", tool_calls=tool_calls),
            usage=Usage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            ),
        )


def _parse_arguments(call) -> dict:
    """把模型给出的 arguments 字符串解析成 dict。

    解析失败时把原文塞进 _raw，让工具报"缺少参数"从而触发模型重试，
    而不是让整个循环崩掉。
    """
    raw_args = getattr(call.function, "arguments", "") or ""
    try:
        parsed = json.loads(raw_args)
        return parsed if isinstance(parsed, dict) else {"_raw": raw_args}
    except (json.JSONDecodeError, TypeError):
        return {"_raw": raw_args}
