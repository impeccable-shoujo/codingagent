"""终端入口：v0.1 先用命令行把闭环跑通，Web 界面是后面的事。

先用 REPL 是有意的：终端里能第一时间看到 agent 的真实行为，
包括失败、截断、卡循环这些"丑陋状态"——它们才是设计前端状态的依据。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loop import AgentLoop, LoopConfig
from .log import NullLogger, RunLogger
from .provider import OpenAICompatProvider, ProviderError
from .tools import CommandGuard, ToolContext, build_default_tools
from .types import AgentEvent

BANNER = """coding agent v0.1 — 输入任务后回车执行，输入 exit 退出。
工作区：{workspace}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="最小可用的 coding agent")
    parser.add_argument("-t", "--task", help="直接执行一次任务后退出；不给则进入交互模式")
    parser.add_argument("-w", "--workspace", default=".", help="工作区根目录，默认当前目录")
    parser.add_argument("-m", "--model", default="glm-4.7-flash", help="模型名")
    parser.add_argument("--base-url", default=None, help="OpenAI 兼容端点")
    parser.add_argument("--api-key-env", default="ZHIPU_API_KEY", help="存放 API Key 的环境变量名")
    parser.add_argument("--max-iterations", type=int, default=25, help="最大迭代轮数")
    parser.add_argument("--no-log", action="store_true", help="不写 jsonl 会话日志")
    parser.add_argument("--log-dir", default="runs", help="会话日志目录")
    parser.add_argument("-y", "--yes", action="store_true", help="需要确认的命令自动批准（谨慎）")
    parser.add_argument("-q", "--quiet", action="store_true", help="只打印最终结果")
    return parser


def render(event: AgentEvent, quiet: bool = False) -> None:
    kind = event.type
    data = event.data

    if kind == "iteration_start":
        if not quiet:
            print(f"\n──── 第 {data['iteration']} 轮 ────")
    elif kind == "assistant_message":
        if data.get("content"):
            print(data["content"])
        if data.get("tool_calls") and not quiet:
            print(f"  调用工具：{', '.join(data['tool_calls'])}")
    elif kind == "tool_start" and not quiet:
        args = data.get("arguments") or {}
        brief = str(args)[:200]
        print(f"  ▶ {data['name']}({brief})")
    elif kind == "tool_result":
        mark = "✓" if data.get("ok") else "✗"
        content = (data.get("content") or "").strip() or "(无输出)"
        if quiet:
            return
        preview = content if len(content) <= 800 else content[:800] + "\n...[预览已截断]"
        print(f"  {mark} {data['name']}")
        for line in preview.splitlines():
            print(f"     {line}")
    elif kind == "error":
        print(f"\n[错误] {data.get('message')}")
    elif kind == "done":
        reason = data.get("reason")
        if reason != "completed":
            print(f"\n[停止原因] {reason}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"工作区不存在：{workspace}", file=sys.stderr)
        return 1

    guard = CommandGuard()

    def approval(command: str) -> bool:
        if args.yes:
            return True
        try:
            answer = input(f"\n  需要确认：{command}\n  允许执行？[y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    ctx = ToolContext(workspace=workspace, guard=guard, approval=approval)
    tools = build_default_tools(ctx)

    try:
        provider = OpenAICompatProvider(
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
        )
    except ProviderError as exc:
        print(f"无法初始化模型：{exc}", file=sys.stderr)
        return 1

    logger = NullLogger() if args.no_log else RunLogger(args.log_dir)
    loop = AgentLoop(
        provider=provider,
        tools=tools,
        config=LoopConfig(max_iterations=args.max_iterations),
        logger=logger,
        sink=lambda e: render(e, quiet=args.quiet),
    )

    if args.task:
        result = loop.run(args.task)
        print(f"\n=== 结果（{result.stop_reason}，{result.iterations} 轮，"
              f"{result.usage.total_tokens} tokens）===\n{result.text}")
        logger.close()
        return 0 if result.succeeded else 2

    print(BANNER.format(workspace=workspace))
    while True:
        try:
            task = input("\n任务> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if task.lower() in ("exit", "quit", "q"):
            break
        if not task:
            continue
        result = loop.run(task)
        print(f"\n=== 结果（{result.stop_reason}，{result.iterations} 轮，"
              f"{result.usage.total_tokens} tokens）===\n{result.text}")

    logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
