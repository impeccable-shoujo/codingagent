"""把工具装配成注册表。主循环只依赖 ToolRegistry，不关心具体有几个工具。"""

from __future__ import annotations

from .base import ToolContext, ToolRegistry
from .bash import build_bash_tool
from .read_file import build_read_file_tool
from .write_file import build_write_file_tool


def build_default_tools(ctx: ToolContext) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(build_read_file_tool(ctx))
    registry.register(build_write_file_tool(ctx))
    registry.register(build_bash_tool(ctx))
    return registry
