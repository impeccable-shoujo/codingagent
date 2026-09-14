"""bash：能力最强也最危险的工具。

它能跑测试、grep、git、装依赖 —— 这个 agent 大约八成的能力都来自它。
所以执行前必须经过 CommandGuard 的三档检查，且进程工作目录锁定在工作区。
"""

from __future__ import annotations

import os
import subprocess

from ..util import decode_output, interpreter_path_dirs
from .base import Tool, ToolContext, ToolResult, truncate_output
from .guard import GuardAction

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的 shell 命令"},
        "timeout": {"type": "integer", "description": "超时秒数，默认 60，上限 300"},
    },
    "required": ["command"],
}

MAX_TIMEOUT = 300


def _subprocess_env() -> dict[str, str]:
    """让命令跑在和 agent 同一个 Python 环境里。

    只把命令写成绝对路径是不够的：子进程解析 `python` / `pytest` 看的是 PATH，
    所以这里把当前解释器所在环境的目录 prepend 上去。否则 agent 在项目虚拟环境里
    运行、子进程却在别的 Python 上跑，会报出莫名其妙的 "No module named pytest"。
    """
    env = os.environ.copy()
    prefix = os.pathsep.join(str(path) for path in interpreter_path_dirs())
    existing = env.get("PATH", "")
    env["PATH"] = f"{prefix}{os.pathsep}{existing}" if existing else prefix
    return env


def build_bash_tool(ctx: ToolContext) -> Tool:
    def _bash(args: dict) -> ToolResult:
        command = args.get("command")
        if not command:
            return ToolResult(ok=False, error="缺少参数 command")
        command = str(command)

        guard = ctx.guard
        if guard is not None:
            decision = guard.check(command)
            if decision.action is GuardAction.DENY:
                return ToolResult(ok=False, error=decision.reason)
            if decision.action is GuardAction.ASK:
                approved = bool(ctx.approval(command)) if ctx.approval else False
                if not approved:
                    return ToolResult(ok=False, error=f"未获批准，已取消执行：{command}")

        timeout = min(int(args.get("timeout") or ctx.timeout), MAX_TIMEOUT)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(ctx.workspace),
                capture_output=True,
                timeout=timeout,
                env=_subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"命令超时（{timeout}s）：{command}")
        except OSError as exc:
            return ToolResult(ok=False, error=f"执行失败：{exc}")

        output = decode_output(proc.stdout or b"") + decode_output(proc.stderr or b"")
        output, truncated = truncate_output(output, ctx.max_chars, ctx.max_lines)

        if proc.returncode == 0:
            note = " [输出已截断]" if truncated else ""
            return ToolResult(ok=True, output=(output or "(无输出)") + note, truncated=truncated)

        error = f"退出码 {proc.returncode}\n{output}".strip()
        if truncated:
            error += "\n[输出已截断]"
        return ToolResult(ok=False, output=output, error=error, truncated=truncated)

    return Tool(
        name="bash",
        description=(
            "在工作区内执行 shell 命令，可用来跑测试、搜索代码、执行 git。"
            "删除类、git 写操作、安装依赖等命令需要用户确认；危险命令会被直接拒绝。"
        ),
        parameters=PARAMETERS,
        fn=_bash,
    )
