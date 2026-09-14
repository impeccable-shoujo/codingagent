"""终端入口：v0.1 先用命令行把闭环跑通，Web 界面是后面的事。

先用 REPL 是有意的：终端里能第一时间看到 agent 的真实行为，
包括失败、截断、卡循环这些"丑陋状态"——它们才是设计前端状态的依据。

参数来源：命令行只负责"覆盖"，默认值一律来自 .env / 环境变量（见 config.py）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .app import build_agent
from .config import DEFAULT_ENV_FILE, ConfigError, Settings, describe
from .provider import ProviderError
from .types import AgentEvent

BANNER = """coding agent v0.1 — 输入任务后回车执行，输入 exit 退出。
工作区：{workspace}
模型：{model}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="最小可用的 coding agent（默认配置从 .env 读取，命令行参数用于临时覆盖）",
    )
    parser.add_argument("-t", "--task", default=None, help="直接执行一次任务后退出；不给则进入交互模式")
    parser.add_argument("--env-file", default=None, help=f".env 文件路径，默认 {DEFAULT_ENV_FILE}")
    parser.add_argument("--show-config", action="store_true", help="打印生效配置后退出")
    parser.add_argument("-w", "--workspace", default=None, help="覆盖工作区根目录")
    parser.add_argument("-m", "--model", default=None, help="覆盖模型名")
    parser.add_argument("--base-url", default=None, help="覆盖 OpenAI 兼容端点")
    parser.add_argument("--api-key", default=None, help="直接传密钥（会留在 shell 历史里，不推荐）")
    parser.add_argument("--max-iterations", type=int, default=None, help="覆盖最大迭代轮数")
    parser.add_argument("--log-dir", default=None, help="覆盖会话日志目录")
    parser.add_argument("--no-log", action="store_true", help="不写 jsonl 会话日志")
    parser.add_argument("-y", "--yes", action="store_true", help="需确认的命令自动批准（谨慎）")
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
        brief = str(data.get("arguments") or {})[:200]
        print(f"  ▶ {data['name']}({brief})")
    elif kind == "tool_result":
        if quiet:
            return
        mark = "✓" if data.get("ok") else "✗"
        content = (data.get("content") or "").strip() or "(无输出)"
        preview = content if len(content) <= 800 else content[:800] + "\n...[预览已截断]"
        print(f"  {mark} {data['name']}")
        for line in preview.splitlines():
            print(f"     {line}")
    elif kind == "error":
        print(f"\n[错误] {data.get('message')}")
    elif kind == "done":
        if data.get("reason") != "completed":
            print(f"\n[停止原因] {data.get('reason')}")


def _apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    overrides: dict = {}
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    if args.workspace:
        overrides["workspace"] = Path(args.workspace)
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.log_dir:
        overrides["log_dir"] = Path(args.log_dir)
    if args.yes:
        overrides["auto_approve"] = True
    return replace(settings, **overrides) if overrides else settings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_file = args.env_file if args.env_file is not None else DEFAULT_ENV_FILE

    try:
        settings = _apply_cli_overrides(Settings.from_env(env_file=env_file), args)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    if args.show_config:
        print(describe(settings))
        return 0

    workspace = Path(settings.workspace).resolve()
    if not workspace.is_dir():
        print(f"工作区不存在：{workspace}", file=sys.stderr)
        return 1

    def interactive_approval(command: str) -> bool:
        try:
            answer = input(f"\n  需要确认：{command}\n  允许执行？[y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    try:
        loop = build_agent(
            settings,
            approval=None if settings.auto_approve else interactive_approval,
            sink=lambda event: render(event, quiet=args.quiet),
            with_log=not args.no_log,
        )
    except ProviderError as exc:
        print(f"无法初始化模型：{exc}", file=sys.stderr)
        print("提示：把密钥写进 .env 的 AGENT_API_KEY，或设置系统环境变量 ZHIPU_API_KEY。"
              "可用 --show-config 检查配置是否生效。", file=sys.stderr)
        return 1

    def report(result) -> None:
        print(f"\n=== 结果（{result.stop_reason}，{result.iterations} 轮，"
              f"{result.usage.total_tokens} tokens）===\n{result.text}")

    try:
        if args.task:
            result = loop.run(args.task)
            report(result)
            return 0 if result.succeeded else 2

        print(BANNER.format(workspace=workspace, model=settings.model))
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
            report(loop.run(task))
    finally:
        if loop.logger is not None:
            loop.logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
