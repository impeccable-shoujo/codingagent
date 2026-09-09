"""工具层基础设施：结果类型、输出截断、工作区越界防护、工具注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class ToolError(Exception):
    """工具执行失败。会被主循环捕获并转成给模型的错误信息，不会中断整个循环。"""


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    error: str | None = None
    truncated: bool = False

    def to_content(self) -> str:
        """转成喂回模型的内容。失败时带上 ERROR 前缀，便于模型识别并自我修正。"""
        if self.ok:
            return self.output
        return f"ERROR: {self.error}"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[[dict], ToolResult]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"未知工具：{name}。可用工具：{', '.join(self._tools)}")
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def truncate_output(text: str, max_chars: int, max_lines: int) -> tuple[str, bool]:
    """截断超长输出，保留头尾，中间插入省略标记。

    为什么保留头尾：命令输出的关键信息通常在开头（报错类型）和结尾（最终结果），
    砍中间对模型的判断影响最小。
    """
    original = text

    lines = text.splitlines()
    if len(lines) > max_lines:
        head_n = max_lines // 2
        tail_n = max_lines - head_n
        omitted = len(lines) - head_n - tail_n
        text = "\n".join(
            lines[:head_n] + [f"...[已省略 {omitted} 行]..."] + lines[len(lines) - tail_n :]
        )

    if len(text) > max_chars:
        head_n = max_chars // 2
        tail_n = max_chars - head_n
        omitted = len(text) - head_n - tail_n
        text = text[:head_n] + f"\n...[已省略 {omitted} 字符]...\n" + text[len(text) - tail_n :]

    return text, text != original


def resolve_in_workspace(workspace: Path, raw: str) -> Path:
    """把用户/模型给的路径限制在工作区内，阻止 ../ 或绝对路径逃逸。

    这是安全边界的第一道：即使模型被 prompt 注入诱导去读 /etc/passwd，
    也只会得到一个越界错误。
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    root = workspace.resolve()
    if resolved != root and root not in resolved.parents:
        raise ToolError(f"路径越界：{raw} 不在工作区 {root} 内")
    return resolved


@dataclass
class ToolContext:
    """工具执行时需要的上下文，由主循环注入，避免用全局变量。"""

    workspace: Path
    max_chars: int = 10_000
    max_lines: int = 200
    timeout: int = 60
    guard: "object | None" = None
    approval: Callable[[str], bool] | None = None
    extra: dict = field(default_factory=dict)
