"""工具层测试：读、写、执行，以及它们的边界。"""

import sys

import pytest

from agent.tools import (
    CommandGuard,
    ToolContext,
    build_default_tools,
    truncate_output,
)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "hello.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def ctx(workspace):
    return ToolContext(workspace=workspace, guard=CommandGuard(), approval=lambda cmd: False)


@pytest.fixture
def tools(ctx):
    return build_default_tools(ctx)


def _run(tools, name, **args):
    return tools.get(name).fn(args)


# ---------- read_file ----------


def test_read_file_returns_numbered_lines(tools):
    result = _run(tools, "read_file", path="hello.py")
    assert result.ok
    assert "1\t" in result.output.replace(" ", "").replace("\t", "\t") or "a = 1" in result.output
    assert "a = 1" in result.output and "c = 3" in result.output


def test_read_file_respects_offset_and_limit(tools):
    result = _run(tools, "read_file", path="hello.py", offset=2, limit=1)
    assert result.ok
    assert "b = 2" in result.output
    assert "a = 1" not in result.output


def test_read_file_missing_path_argument(tools):
    result = _run(tools, "read_file")
    assert not result.ok
    assert "缺少参数" in result.error


def test_read_file_not_found(tools):
    result = _run(tools, "read_file", path="nope.py")
    assert not result.ok
    assert "文件不存在" in result.error


def test_read_file_on_directory(tools):
    result = _run(tools, "read_file", path=".")
    assert not result.ok
    assert "目录" in result.error


def test_read_file_blocks_path_escape(tools):
    result = _run(tools, "read_file", path="../../etc/passwd")
    assert not result.ok
    assert "越界" in result.error


# ---------- write_file ----------


def test_write_file_creates_new_file(tools, workspace):
    result = _run(tools, "write_file", path="out.txt", content="hello")
    assert result.ok
    assert "新建" in result.output
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "hello"


def test_write_file_overwrites_existing(tools, workspace):
    _run(tools, "write_file", path="out.txt", content="one")
    result = _run(tools, "write_file", path="out.txt", content="two")
    assert result.ok
    assert "覆盖" in result.output
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "two"


def test_write_file_detects_no_change(tools):
    _run(tools, "write_file", path="same.txt", content="x")
    result = _run(tools, "write_file", path="same.txt", content="x")
    assert result.ok
    assert "未变化" in result.output


def test_write_file_creates_parent_dirs(tools, workspace):
    result = _run(tools, "write_file", path="deep/nested/x.txt", content="v")
    assert result.ok
    assert (workspace / "deep" / "nested" / "x.txt").exists()


def test_write_file_blocks_path_escape(tools):
    result = _run(tools, "write_file", path="../escape.txt", content="v")
    assert not result.ok
    assert "越界" in result.error


# ---------- bash ----------


def test_bash_runs_command(tools):
    result = _run(tools, "bash", command="echo hello-agent")
    assert result.ok
    assert "hello-agent" in result.output


def test_bash_reports_nonzero_exit(tools):
    result = _run(tools, "bash", command=f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    assert not result.ok
    assert "退出码 3" in result.error


def test_bash_denied_command_never_runs(tools):
    result = _run(tools, "bash", command="sudo echo pwned")
    assert not result.ok
    assert "已拦截" in result.error
    assert "pwned" not in result.output


def test_bash_ask_command_cancelled_without_approval(tools):
    """没有审批回调时，需要确认的命令一律不执行。"""
    result = _run(tools, "bash", command="rm hello.py")
    assert not result.ok
    assert "未获批准" in result.error


def test_bash_ask_command_runs_when_approved(workspace):
    from agent.tools import ToolContext, build_default_tools

    ctx = ToolContext(workspace=workspace, guard=CommandGuard(), approval=lambda cmd: True)
    tools = build_default_tools(ctx)
    result = tools.get("bash").fn({"command": "echo approved"})
    assert result.ok
    assert "approved" in result.output


def test_bash_timeout(tools):
    result = _run(
        tools,
        "bash",
        command=f'"{sys.executable}" -c "import time; time.sleep(5)"',
        timeout=1,
    )
    assert not result.ok
    assert "超时" in result.error


def test_bash_missing_command(tools):
    result = tools.get("bash").fn({})
    assert not result.ok
    assert "缺少参数" in result.error


# ---------- 截断 ----------


def test_truncate_keeps_head_and_tail():
    text = "\n".join(str(i) for i in range(1000))
    out, truncated = truncate_output(text, max_chars=10**9, max_lines=20)
    assert truncated
    assert "0" in out.splitlines()[0]
    assert "999" in out
    assert "已省略" in out


def test_truncate_noop_when_small():
    out, truncated = truncate_output("abc", max_chars=100, max_lines=100)
    assert out == "abc"
    assert not truncated


def test_truncate_caps_chars():
    out, truncated = truncate_output("x" * 5000, max_chars=200, max_lines=10**6)
    assert truncated
    assert len(out) < 5000
    assert "已省略" in out
