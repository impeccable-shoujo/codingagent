"""传输层测试：TestClient + ScriptedProvider，全程不碰网络。

SSE 是流式的、TestClient 是同步的，两者能配合的前提是：会话结束时服务端会
推送终止信号、客户端主动断开。这个前提不成立的话测试会死等，所以下面专门
有一项测试盯着"晚订阅也能拿到完整历史并正常结束"。
"""

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from agent.config import Settings  # noqa: E402
from agent.provider.scripted import ScriptedProvider  # noqa: E402
from agent.server.main import create_app, format_sse  # noqa: E402
from agent.types import AgentEvent, Message, ToolCall  # noqa: E402


def tool_call(name: str, **arguments) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=f"c-{name}-{len(arguments)}", name=name, arguments=arguments)],
    )


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(api_key="sk-test-key", workspace=tmp_path, log_dir=tmp_path / "logs")
    base.update(overrides)
    return Settings(**base)


def make_client(tmp_path, script=None, final_text="完成", **overrides):
    settings = make_settings(tmp_path, **overrides)
    provider = ScriptedProvider(script=script or [], final_text=final_text)
    app = create_app(settings=settings, provider_factory=lambda s: provider)
    return TestClient(app), provider


def run_task(client, task="做点什么") -> str:
    response = client.post("/tasks", json={"task": task})
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """解析 SSE 响应，返回 (事件类型, 事件负载)。

    帧里 data 行是完整信封 {"type","ts","data"}，这里剥掉外层，
    让断言直接针对业务负载——信封本身另有专门的格式测试盯着。
    """
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        kind, envelope = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: ") :]
            elif line.startswith("data: "):
                envelope = json.loads(line[len("data: ") :])
        if kind:
            events.append((kind, (envelope or {}).get("data", {})))
    return events


def read_stream(client, task_id: str) -> list[tuple[str, dict]]:
    response = client.get(f"/stream?task_id={task_id}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("等待超时")


# ---------- 基础接口 ----------


def test_index_lists_endpoints(tmp_path):
    client, _ = make_client(tmp_path)
    body = client.get("/").json()
    assert "POST /tasks" in body["endpoints"]
    assert body["model"] == "glm-4.5-air"


def test_health_reports_workspace_and_model(tmp_path):
    client, _ = make_client(tmp_path)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert str(tmp_path) in body["workspace"]
    assert body["sessions"] == 0


def test_empty_task_is_rejected(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/tasks", json={"task": ""}).status_code == 422
    assert client.post("/tasks", json={}).status_code == 422


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/stream?task_id=nope", None),
        ("get", "/tasks/nope", None),
        ("post", "/approve", {"task_id": "nope", "approval_id": "x", "approved": True}),
        ("post", "/stop", {"task_id": "nope"}),
    ],
)
def test_unknown_task_returns_404(tmp_path, method, path, payload):
    client, _ = make_client(tmp_path)
    response = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
    assert response.status_code == 404


# ---------- 任务执行与事件流 ----------


def test_task_runs_to_completion_and_streams_events(tmp_path):
    client, _ = make_client(
        tmp_path,
        script=[tool_call("write_file", path="out.txt", content="hello")],
        final_text="写好了",
    )
    task_id = run_task(client, "写个文件")
    events = read_stream(client, task_id)
    kinds = [kind for kind, _ in events]

    assert kinds[0] == "iteration_start"
    assert "tool_start" in kinds and "tool_result" in kinds
    assert kinds[-1] == "done"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"

    done = dict(events)["done"]
    assert done["reason"] == "completed"
    assert done["text"] == "写好了"


def test_stream_replays_history_for_late_subscriber(tmp_path):
    """晚连的客户端不能漏掉前面发生了什么——这是 SSE + 历史回放的关键约束。"""
    client, _ = make_client(tmp_path, script=[tool_call("write_file", path="a.txt", content="x")])
    task_id = run_task(client)

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "completed")

    events = read_stream(client, task_id)
    kinds = [kind for kind, _ in events]
    assert "iteration_start" in kinds
    assert kinds[-1] == "done"


def test_task_detail_reports_usage(tmp_path):
    client, _ = make_client(tmp_path, script=[tool_call("write_file", path="a.txt", content="x")])
    task_id = run_task(client)
    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "completed")

    snapshot = client.get(f"/tasks/{task_id}").json()
    assert snapshot["iterations"] == 2
    assert snapshot["tokens"] == 0  # ScriptedProvider 不产生用量
    assert snapshot["text"] == "完成"
    assert snapshot["pending_approvals"] == []


def test_task_waiting_for_approval_is_visible_in_snapshot(tmp_path):
    """刷新页面后仍要能看到待确认的审批，否则任务会一直卡到超时。"""
    (tmp_path / "victim.txt").write_text("x", encoding="utf-8")
    client, _ = make_client(tmp_path, script=[tool_call("bash", command="rm victim.txt")])
    task_id = run_task(client)

    approval_id = wait_for(
        lambda: (client.get(f"/tasks/{task_id}").json()["pending_approvals"] or [None])[0]
    )
    assert approval_id

    client.post(
        "/approve",
        json={"task_id": task_id, "approval_id": approval_id, "approved": True},
    )
    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] != "running")

    assert not (tmp_path / "victim.txt").exists()
    kinds = [kind for kind, _ in read_stream(client, task_id)]
    assert "approval_required" in kinds


# ---------- 审批 ----------


def test_approval_granted_executes_command(tmp_path):
    (tmp_path / "victim.txt").write_text("x", encoding="utf-8")
    client, _ = make_client(tmp_path, script=[tool_call("bash", command="rm victim.txt")])
    task_id = run_task(client)

    approval_id = wait_for(
        lambda: (client.get(f"/tasks/{task_id}").json()["pending_approvals"] or [None])[0]
    )
    response = client.post(
        "/approve", json={"task_id": task_id, "approval_id": approval_id, "approved": True}
    )
    assert response.status_code == 200

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "completed")
    assert not (tmp_path / "victim.txt").exists()


def test_approval_denied_keeps_side_effects_away(tmp_path):
    (tmp_path / "victim.txt").write_text("x", encoding="utf-8")
    client, _ = make_client(tmp_path, script=[tool_call("bash", command="rm victim.txt")])
    task_id = run_task(client)

    approval_id = wait_for(
        lambda: (client.get(f"/tasks/{task_id}").json()["pending_approvals"] or [None])[0]
    )
    client.post(
        "/approve", json={"task_id": task_id, "approval_id": approval_id, "approved": False}
    )

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] != "running")
    assert (tmp_path / "victim.txt").exists(), "被拒绝的命令绝不能产生副作用"
    contents = [data.get("content", "") for kind, data in read_stream(client, task_id) if kind == "tool_result"]
    assert any("未获批准" in item for item in contents)


def test_approval_times_out_as_denied(tmp_path):
    """没人应答时按拒绝处理：宁可少做一步，也不要擅自执行危险命令。"""
    (tmp_path / "victim.txt").write_text("x", encoding="utf-8")
    client, _ = make_client(
        tmp_path,
        script=[tool_call("bash", command="rm victim.txt")],
        approval_timeout=1,
    )
    task_id = run_task(client)

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] != "running", timeout=10)
    assert (tmp_path / "victim.txt").exists()
    kinds = [kind for kind, _ in read_stream(client, task_id)]
    assert "approval_timeout" in kinds


def test_approving_unknown_request_returns_404(tmp_path):
    client, _ = make_client(tmp_path, script=[tool_call("write_file", path="a.txt", content="x")])
    task_id = run_task(client)
    response = client.post(
        "/approve", json={"task_id": task_id, "approval_id": "not-a-real-id", "approved": True}
    )
    assert response.status_code == 404


def test_hard_denied_command_is_never_sent_for_approval(tmp_path):
    """DENY 档要绕过审批直接拒绝，不能退化成"问一下用户"。"""
    client, _ = make_client(tmp_path, script=[tool_call("bash", command="sudo rm -rf /")])
    task_id = run_task(client)
    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] != "running")

    kinds = [kind for kind, _ in read_stream(client, task_id)]
    assert "approval_required" not in kinds
    contents = [data.get("content", "") for kind, data in read_stream(client, task_id) if kind == "tool_result"]
    assert any("已拦截" in item for item in contents)


# ---------- 中断 ----------


def test_stop_interrupts_running_task(tmp_path):
    release = threading.Event()

    def blocking(index, messages):
        # 卡在第二轮，给测试留出调用 /stop 的窗口
        release.wait(timeout=10)
        return tool_call("bash", command="echo late")

    client, _ = make_client(
        tmp_path,
        script=[tool_call("bash", command="echo first"), blocking],
        max_iterations=20,
    )
    task_id = run_task(client)

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["events"] >= 3)
    assert client.post("/stop", json={"task_id": task_id}).status_code == 200
    release.set()

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "stopped")
    kinds = [kind for kind, _ in read_stream(client, task_id)]
    assert "interrupted" in kinds
    assert "echo late" not in json.dumps(read_stream(client, task_id), ensure_ascii=False)


def test_stop_releases_pending_approval(tmp_path):
    """中断时必须放掉等待中的审批，否则 worker 线程会一直挂在 gate 上。"""
    (tmp_path / "victim.txt").write_text("x", encoding="utf-8")
    client, _ = make_client(tmp_path, script=[tool_call("bash", command="rm victim.txt")])
    task_id = run_task(client)

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["pending_approvals"])
    client.post("/stop", json={"task_id": task_id})

    wait_for(lambda: client.get(f"/tasks/{task_id}").json()["status"] == "stopped", timeout=10)
    assert (tmp_path / "victim.txt").exists()


# ---------- SSE 帧格式 ----------


def test_format_sse_frame_structure():
    frame = format_sse(AgentEvent(type="tool_result", data={"content": "line1\nline2"}))

    assert frame.startswith("event: tool_result\ndata: ")
    assert frame.endswith("\n\n")
    body = frame.split("data: ", 1)[1].strip()
    assert "\n" not in body, "data 行必须是单行，裸换行会截断 SSE 帧"
    assert json.loads(body)["data"]["content"] == "line1\nline2"


def test_format_sse_carries_full_envelope():
    """信封带 type 和 ts，前端不必只靠 event 行判断类型，也方便算耗时。"""
    frame = format_sse(AgentEvent(type="done", data={"reason": "completed"}))
    envelope = json.loads(frame.split("data: ", 1)[1].strip())

    assert envelope["type"] == "done"
    assert isinstance(envelope["ts"], float)
    assert envelope["data"]["reason"] == "completed"


def test_format_sse_keeps_chinese_readable():
    frame = format_sse(AgentEvent(type="done", data={"text": "已完成"}))
    assert "已完成" in frame, "不应被转义成 \\uXXXX，否则前端调试很难读"
