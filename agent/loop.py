"""Agent 主循环：LLM 决策 -> 调工具 -> 结果回填 -> 再决策。

这是整个系统唯一有"智能"的地方，其余都是可替换的零件。
循环里所有出口都必须有明确原因，方便外部判断该重试、该问人还是该放弃。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .provider.base import ProviderError
from .tools.base import ToolRegistry, ToolResult
from .types import AgentEvent, Message, ToolCall, Usage

DEFAULT_SYSTEM_PROMPT = """你是一个在用户代码仓库里工作的 coding agent。

工作原则：
1. 先看清再动手。用 read_file 和 bash 找到相关代码，不要凭猜测修改。
2. 改动必须被验证。改完用 bash 跑测试或运行脚本确认效果，不要口头声称完成。
3. 小步前进。一次只改一处，改完立即验证，失败就根据报错修正方向。
4. 不确定就问。需要删除文件、执行 git 写操作时，系统会征求用户确认。
5. 不要尝试危险命令。删根目录、强制推送、提权等操作会被系统直接拒绝。

所有路径都相对工作区根目录，不要使用绝对路径或 ../ 逃逸。
完成标准：验证通过，并在最终回复里简要说明改了什么、怎么验证的。"""

STOPPED_TEXT = "任务已被中断。"


@dataclass
class LoopConfig:
    max_iterations: int = 25
    max_consecutive_failures: int = 3
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


@dataclass
class RunResult:
    text: str
    stop_reason: str
    iterations: int
    usage: Usage = field(default_factory=Usage)
    messages: list[Message] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.stop_reason == "completed"


class AgentLoop:
    def __init__(
        self,
        provider,
        tools: ToolRegistry,
        config: LoopConfig | None = None,
        logger=None,
        sink=None,
        should_stop=None,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.config = config or LoopConfig()
        self.logger = logger
        self.sink = sink
        self.should_stop = should_stop

    def interrupted(self) -> bool:
        """外部中断信号。

        做成可注入的回调而不是内部标志位：调用方可能是终端里的 Ctrl+C，
        也可能是 HTTP 层的 /stop，主循环不该关心中断从哪来。
        """
        return bool(self.should_stop and self.should_stop())

    def _emit(self, type_: str, **data) -> AgentEvent:
        event = AgentEvent(type=type_, data=data)
        if self.logger is not None:
            self.logger.emit(event)
        if self.sink is not None:
            self.sink(event)
        return event

    def run(self, task: str) -> RunResult:
        cfg = self.config
        messages: list[Message] = [
            Message(role="system", content=cfg.system_prompt),
            Message(role="user", content=task),
        ]
        usage = Usage()
        events: list[AgentEvent] = []
        consecutive_failures = 0
        final_text = ""
        stop_reason = "completed"
        iterations = 0

        for iteration in range(1, cfg.max_iterations + 1):
            iterations = iteration

            if self.interrupted():
                stop_reason, final_text = "stopped", STOPPED_TEXT
                events.append(self._emit("interrupted", reason=stop_reason))
                break

            events.append(self._emit("iteration_start", iteration=iteration))

            try:
                response = self.provider.chat(messages, self.tools.schemas())
            except ProviderError as exc:
                stop_reason = "provider_error"
                final_text = f"模型调用失败：{exc}"
                events.append(self._emit("error", reason=stop_reason, message=str(exc)))
                break

            usage.prompt_tokens += response.usage.prompt_tokens
            usage.completion_tokens += response.usage.completion_tokens

            assistant = response.message
            messages.append(assistant)
            events.append(self._emit("assistant_message", content=assistant.content,
                                     tool_calls=[c.name for c in assistant.tool_calls]))

            if not assistant.tool_calls:
                final_text = assistant.content
                stop_reason = "completed"
                break

            for call in assistant.tool_calls:
                if self.interrupted():
                    stop_reason, final_text = "stopped", STOPPED_TEXT
                    events.append(self._emit("interrupted", reason=stop_reason))
                    break

                result = self._execute(call)
                events.append(self._emit(
                    "tool_result",
                    name=call.name,
                    ok=result.ok,
                    truncated=result.truncated,
                    content=result.to_content(),
                ))
                messages.append(Message.tool_result(call.id, call.name, result.to_content()))

                consecutive_failures = 0 if result.ok else consecutive_failures + 1
                if consecutive_failures >= cfg.max_consecutive_failures:
                    break

            if stop_reason == "stopped":
                break
            if consecutive_failures >= cfg.max_consecutive_failures:
                stop_reason = "consecutive_failures"
                final_text = (
                    f"连续 {consecutive_failures} 次工具调用失败，已停止。"
                    "请根据上面的错误信息调整任务描述后重试。"
                )
                break
            if iteration == cfg.max_iterations:
                stop_reason = "max_iterations"
                final_text = f"已达到最大迭代次数 {cfg.max_iterations}，任务可能未完成。"
        else:
            stop_reason = "max_iterations"

        # done 带上轮次与用量：前端状态栏要显示"跑了几轮、花了多少 token"，
        # 有这两个字段就不必再回查一次任务快照。
        events.append(
            self._emit(
                "done",
                reason=stop_reason,
                text=final_text,
                iterations=iterations,
                usage={
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                },
            )
        )
        return RunResult(
            text=final_text,
            stop_reason=stop_reason,
            iterations=iterations,
            usage=usage,
            messages=messages,
            events=events,
        )

    def _execute(self, call: ToolCall) -> ToolResult:
        self._emit("tool_start", name=call.name, arguments=call.arguments)
        try:
            tool = self.tools.get(call.name)
            result = tool.fn(call.arguments or {})
        except Exception as exc:  # 工具自身抛异常也要让模型看到，不能直接崩掉循环
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        if not isinstance(result, ToolResult):
            return ToolResult(ok=False, error=f"工具 {call.name} 返回了非法结果类型")
        return result
