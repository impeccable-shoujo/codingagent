"""组装根：把 Settings 变成可直接运行的对象。

CLI 和后续的 FastAPI 传输层都从这里取 agent，接线逻辑只写一遍。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Settings
from .log import NullLogger, RunLogger
from .loop import AgentLoop, LoopConfig
from .provider import OpenAICompatProvider
from .tools import CommandGuard, ToolContext, build_default_tools


def build_provider(settings: Settings) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
    )


def build_agent(
    settings: Settings,
    approval: Callable[[str], bool] | None = None,
    sink: Callable | None = None,
    logger=None,
    with_log: bool = True,
) -> AgentLoop:
    """装配一个可运行的 agent。

    approval 为 None 时的默认行为是**拒绝**所有需确认命令，
    除非显式打开 auto_approve。对未来的 HTTP 层来说这个默认值是安全的：
    没有接上审批 UI 之前，危险命令不会被执行。
    """
    if approval is None:
        approval = (lambda command: True) if settings.auto_approve else (lambda command: False)

    ctx = ToolContext(
        workspace=Path(settings.workspace).resolve(),
        max_chars=settings.max_output_chars,
        max_lines=settings.max_output_lines,
        timeout=settings.command_timeout,
        guard=CommandGuard(),
        approval=approval,
    )
    tools = build_default_tools(ctx)
    provider = build_provider(settings)

    if logger is None:
        logger = RunLogger(settings.log_dir) if with_log else NullLogger()

    config = LoopConfig(
        max_iterations=settings.max_iterations,
        max_consecutive_failures=settings.max_consecutive_failures,
    )
    return AgentLoop(provider=provider, tools=tools, config=config, logger=logger, sink=sink)
