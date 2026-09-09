"""脚本化 Provider：测试专用。

agent 的非确定性几乎全部来自模型，把这个源头替换成预设脚本，
主循环就变成了一个确定性状态机，可以用纯单测覆盖。
这是这个项目测试策略的核心。
"""

from __future__ import annotations

from typing import Callable, Union

from ..types import LLMResponse, Message
from .base import ModelProvider

ScriptItem = Union[Message, LLMResponse, Callable[..., Union[Message, LLMResponse]]]


class ScriptedProvider(ModelProvider):
    """按脚本逐条返回响应，用尽后返回结束语（无 tool_calls，循环自然终止）。"""

    def __init__(self, script: list[ScriptItem] | None = None, final_text: str = "任务完成") -> None:
        self.name = "scripted"
        self.script: list[ScriptItem] = list(script or [])
        self.final_text = final_text
        self.calls: list[dict] = []

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools})

        if not self.script:
            return LLMResponse(message=Message(role="assistant", content=self.final_text))

        item = self.script.pop(0)
        if callable(item):
            item = item(len(self.calls), messages)
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(message=item)
