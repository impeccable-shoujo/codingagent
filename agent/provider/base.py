"""模型适配层抽象。

主循环只依赖这个接口，不关心底层是智谱、DeepSeek 还是 OpenAI。
好处有两个：换模型零成本；测试时可以注入 ScriptedProvider 做确定性验证。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import LLMResponse, Message


class ModelProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        """发一轮对话，返回助手消息与用量。

        实现方需要把各家 SDK 的返回统一转成 LLMResponse，
        包括解析 tool_calls 的 arguments（字符串 JSON -> dict）。
        """
        raise NotImplementedError


class ProviderError(RuntimeError):
    """模型调用失败（网络、鉴权、限流、返回格式非法等）。"""
