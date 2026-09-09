"""主循环测试：用 ScriptedProvider 把非确定性源头替换掉，循环就成了确定性状态机。"""

import pytest

from agent.loop import AgentLoop, LoopConfig
from agent.provider.base import ProviderError
from agent.provider.scripted import ScriptedProvider
from agent.tools.base import Tool, ToolRegistry, ToolResult
from agent.types import Message, ToolCall, Usage


def make_tool(name: str, ok: bool = True, output: str = "ok") -> Tool:
    calls: list[dict] = []

    def fn(args: dict) -> ToolResult:
        calls.append(args)
        return ToolResult(ok=ok, output=output) if ok else ToolResult(ok=False, error="boom")

    tool = Tool(
        name=name,
        description="测试用工具",
        parameters={"type": "object", "properties": {}},
        fn=fn,
    )
    tool.calls = calls  # type: ignore[attr-defined]
    return tool


def registry_with(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def call(name: str, **arguments) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=f"call-{name}", name=name, arguments=arguments)],
    )


def test_loop_executes_tool_then_finishes():
    tool = make_tool("dummy")
    provider = ScriptedProvider(script=[call("dummy")], final_text="搞定了")
    loop = AgentLoop(provider, registry_with(tool))

    result = loop.run("做点什么")

    assert result.succeeded
    assert result.stop_reason == "completed"
    assert result.text == "搞定了"
    assert result.iterations == 2
    assert len(tool.calls) == 1  # type: ignore[attr-defined]


def test_loop_stops_at_max_iterations():
    tool = make_tool("dummy")
    always_call = lambda i, msgs: call("dummy")  # noqa: E731
    provider = ScriptedProvider(script=[always_call] * 100)
    loop = AgentLoop(provider, registry_with(tool), config=LoopConfig(max_iterations=3))

    result = loop.run("无限循环")

    assert result.stop_reason == "max_iterations"
    assert result.iterations == 3
    assert not result.succeeded


def test_loop_stops_on_consecutive_failures():
    tool = make_tool("dummy", ok=False)
    provider = ScriptedProvider(script=[call("dummy")] * 100)
    loop = AgentLoop(provider, registry_with(tool), config=LoopConfig(max_consecutive_failures=2))

    result = loop.run("一直失败")

    assert result.stop_reason == "consecutive_failures"
    assert not result.succeeded


def test_unknown_tool_reports_error_without_crashing():
    """调用不存在的工具不应中断循环，模型下一轮可以自我纠正。"""
    provider = ScriptedProvider(script=[call("no_such_tool")], final_text="换了个办法")
    loop = AgentLoop(provider, registry_with(make_tool("dummy")))

    result = loop.run("试试看")

    assert result.succeeded
    assert result.iterations == 2
    tool_message = [m for m in result.messages if m.role == "tool"][0]
    assert "未知工具" in tool_message.content


def test_tool_exception_is_captured_as_failure():
    def boom(args: dict) -> ToolResult:
        raise RuntimeError("kaboom")

    tool = Tool(name="boom", description="x", parameters={"type": "object", "properties": {}}, fn=boom)
    provider = ScriptedProvider(script=[call("boom")], final_text="恢复了")
    loop = AgentLoop(provider, registry_with(tool))

    result = loop.run("会炸吗")

    assert result.succeeded
    tool_message = [m for m in result.messages if m.role == "tool"][0]
    assert "kaboom" in tool_message.content


def test_provider_error_stops_loop_cleanly():
    class BrokenProvider(ScriptedProvider):
        def chat(self, messages, tools=None):
            raise ProviderError("网络断了")

    loop = AgentLoop(BrokenProvider(), registry_with(make_tool("dummy")))

    result = loop.run("随便")

    assert result.stop_reason == "provider_error"
    assert "网络断了" in result.text


def test_events_are_emitted_in_order():
    events = []
    provider = ScriptedProvider(script=[call("dummy")], final_text="完")
    loop = AgentLoop(provider, registry_with(make_tool("dummy")), sink=events.append)

    loop.run("跑一轮")

    types = [e.type for e in events]
    assert types[0] == "iteration_start"
    assert "tool_start" in types and "tool_result" in types
    assert types[-1] == "done"
    assert events[-1].data["reason"] == "completed"


def test_usage_is_accumulated():
    tool = make_tool("dummy")
    provider = ScriptedProvider(script=[call("dummy")], final_text="完")

    original_chat = provider.chat

    def chat_with_usage(messages, tools=None):
        response = original_chat(messages, tools)
        response.usage = Usage(prompt_tokens=10, completion_tokens=5)
        return response

    provider.chat = chat_with_usage  # type: ignore[method-assign]
    loop = AgentLoop(provider, registry_with(tool))

    result = loop.run("统计用量")

    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 10
    assert result.usage.total_tokens == 30


@pytest.mark.parametrize("stop_reason", ["completed", "max_iterations", "consecutive_failures"])
def test_every_exit_has_a_reason(stop_reason):
    """循环的每个出口都必须带原因，方便外部决定重试还是问人。"""
    from agent.loop import RunResult

    result = RunResult(text="", stop_reason=stop_reason, iterations=1)
    assert result.stop_reason == stop_reason
    assert result.succeeded is (stop_reason == "completed")
