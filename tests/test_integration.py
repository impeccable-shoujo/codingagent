"""端到端测试：真实工具层 + 真实主循环 + 脚本化模型。

不碰网络、不花 token，但走的是生产代码路径，
所以能验证"接线"是否正确，这是纯单元测试覆盖不到的。
"""

import json

from agent.loop import AgentLoop
from agent.log import RunLogger
from agent.provider.scripted import ScriptedProvider
from agent.tools import CommandGuard, ToolContext, build_default_tools
from agent.types import Message, ToolCall


def tool_call(name: str, **arguments) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=f"call-{name}-{id(arguments)}", name=name, arguments=arguments)],
    )


def make_agent(tmp_path, script, final_text="完成"):
    ctx = ToolContext(workspace=tmp_path, guard=CommandGuard(), approval=lambda c: True)
    tools = build_default_tools(ctx)
    provider = ScriptedProvider(script=script, final_text=final_text)
    return AgentLoop(provider, tools, logger=RunLogger(tmp_path / "logs"))


def test_agent_writes_then_reads_back(tmp_path):
    loop = make_agent(
        tmp_path,
        script=[
            tool_call("write_file", path="answer.txt", content="42"),
            tool_call("read_file", path="answer.txt"),
        ],
    )

    result = loop.run("把答案写进 answer.txt 再读回来")

    assert result.succeeded
    assert (tmp_path / "answer.txt").read_text(encoding="utf-8") == "42"
    tool_outputs = [m.content for m in result.messages if m.role == "tool"]
    assert any("42" in out for out in tool_outputs)


def test_denied_command_never_reaches_the_shell(tmp_path):
    target = tmp_path / "pwned.txt"
    loop = make_agent(
        tmp_path,
        script=[tool_call("bash", command=f'sudo echo pwned > "{target}"')],
    )

    result = loop.run("偷偷越权写文件")

    assert result.succeeded  # 循环本身没崩，只是这一步被拒
    assert not target.exists(), "被拦截的命令决不能产生副作用"
    tool_outputs = [m.content for m in result.messages if m.role == "tool"]
    assert any("已拦截" in out for out in tool_outputs)


def test_agent_recovers_after_a_failed_tool(tmp_path):
    """先读一个不存在的文件，再自己纠正——模拟模型根据报错调整方向。"""
    loop = make_agent(
        tmp_path,
        script=[
            tool_call("read_file", path="missing.py"),
            tool_call("write_file", path="missing.py", content="print('hi')"),
            tool_call("read_file", path="missing.py"),
        ],
    )

    result = loop.run("确保 missing.py 存在并读出内容")

    assert result.succeeded
    outputs = [m.content for m in result.messages if m.role == "tool"]
    assert "文件不存在" in outputs[0]
    assert outputs[1].startswith("已新建") or "新建" in outputs[1]
    assert "print('hi')" in outputs[2]


def test_run_logger_persists_events(tmp_path):
    loop = make_agent(tmp_path, script=[tool_call("write_file", path="x.txt", content="v")])
    loop.run("写个文件")

    log_file = loop.logger.path
    assert log_file.exists()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    kinds = [item["type"] for item in lines]
    assert kinds[0] == "iteration_start"
    assert "tool_result" in kinds
    assert kinds[-1] == "done"


def test_workspace_is_confined(tmp_path):
    """模型试图往外写文件，工具层必须拦下来而不是照做。"""
    loop = make_agent(tmp_path, script=[tool_call("write_file", path="../escape.txt", content="v")])

    result = loop.run("往工作区外写文件")

    assert result.succeeded
    assert not (tmp_path.parent / "escape.txt").exists()
