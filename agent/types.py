"""Agent 的核心数据类型。

这一层定义了整个系统的数据契约：消息、工具调用、用量、事件。
后续 FastAPI 传输层直接把 AgentEvent 序列化成 SSE 推给前端，
所以这里字段一旦变动，前端类型需要同步（用 openapi-typescript 自动生成）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

VALID_ROLES = ("system", "user", "assistant", "tool")


@dataclass
class ToolCall:
    """模型要求调用的一次工具。arguments 是已经解析好的 dict。"""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Message:
    """一条对话消息。role 为 tool 时，tool_call_id 与 name 必填。"""

    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"非法 role: {self.role}，可选值为 {VALID_ROLES}")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("role=tool 的消息必须带 tool_call_id")

    def to_payload(self) -> dict:
        """转成 OpenAI 兼容的请求体格式。"""
        payload: dict = {"role": self.role}
        if self.content:
            payload["content"] = self.content

        if self.role == "assistant" and self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ]
        if self.role == "tool":
            payload["tool_call_id"] = self.tool_call_id
            if self.name:
                payload["name"] = self.name
        return payload

    @classmethod
    def tool_result(cls, call_id: str, name: str, content: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=call_id, name=name)


@dataclass
class LLMResponse:
    """模型适配器统一返回结构，屏蔽各家 SDK 差异。"""

    message: Message
    usage: Usage = field(default_factory=Usage)


@dataclass
class AgentEvent:
    """主循环向外发出的事件，是前后端之间的流式契约。

    type 取值：iteration_start / assistant_message / tool_start /
    tool_result / approval_required / done / error
    """

    type: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"type": self.type, "ts": self.ts, "data": self.data}
