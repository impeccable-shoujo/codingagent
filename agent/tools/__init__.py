"""工具层：把能力封装成模型可调用的 function。"""

from .base import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    resolve_in_workspace,
    truncate_output,
)
from .bash import build_bash_tool
from .factory import build_default_tools
from .guard import CommandGuard, GuardAction, GuardDecision
from .read_file import build_read_file_tool
from .write_file import build_write_file_tool

__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "resolve_in_workspace",
    "truncate_output",
    "CommandGuard",
    "GuardAction",
    "GuardDecision",
    "build_bash_tool",
    "build_read_file_tool",
    "build_write_file_tool",
    "build_default_tools",
]
