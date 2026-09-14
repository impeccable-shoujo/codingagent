"""会话管理：把同步阻塞的 Agent 循环包装成可观察、可打断的后台任务。

设计取舍一——为什么用「线程 + 事件缓冲」而不是把主循环改成 async：
主循环本身是同步阻塞的（subprocess.run、SDK 调用都是阻塞式），改成 async
会一路渗透到工具层和 provider 层。用后台线程跑它，能把改动关在这一层里。

设计取舍二——为什么订阅用「游标 + 轮询」而不是 asyncio.Queue：
worker 是独立线程，要把事件推给 asyncio 侧就得抓住某个事件循环。
但 HTTP 服务里"提交任务"和"订阅事件流"是两个独立请求，它们并不保证跑在
同一个 loop 上，一旦抓错 loop，推送会被静默丢弃、流永远不结束
（这个坑在测试里真实踩到过：连接挂死，直到让连接超时才暴露）。
改成 append-only 事件列表 + 游标轮询后，会话不再绑定任何事件循环，
多个订阅者各自持游标互不干扰。代价是最多几十毫秒的延迟——对 SSE 这种
人类可读的低频事件流完全不可感知。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..types import AgentEvent

TERMINAL_STATUSES = frozenset(
    {"completed", "max_iterations", "consecutive_failures", "provider_error", "stopped", "error"}
)

AgentBuilder = Callable[
    [Callable[[str], bool], Callable[[AgentEvent], None], Callable[[], bool]], object
]


@dataclass
class _PendingApproval:
    """一次等待用户点确认的请求。

    worker 线程阻塞在 gate 上，HTTP 线程调用 resolve_approval 放行。
    超时按「拒绝」处理——宁可少做一步，也不要在无人应答时擅自执行危险命令。
    """

    gate: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class TaskSession:
    def __init__(
        self,
        task: str,
        build_agent: AgentBuilder,
        approval_timeout: int = 300,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.task = task
        self.status = "pending"
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.result = None

        self._build_agent = build_agent
        self._approval_timeout = approval_timeout

        self._events: list[AgentEvent] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._approvals: dict[str, _PendingApproval] = {}
        self._thread = threading.Thread(target=self._run, name=f"agent-{self.id}", daemon=True)

    # ---------- 生命周期 ----------

    def start(self) -> None:
        self._thread.start()

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._is_finished_locked()

    def _is_finished_locked(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    # ---------- 事件订阅 ----------

    def subscribe(self, from_cursor: int = 0) -> int:
        """返回起始游标。默认从 0 开始补齐全部历史；断线重连可传回上次拿到的游标。"""
        return max(0, from_cursor)

    def drain(self, cursor: int) -> tuple[list[AgentEvent], int, bool]:
        """取出 cursor 之后的新事件，并告知会话是否已结束。"""
        with self._lock:
            events = self._events[cursor:]
            return events, len(self._events), self._is_finished_locked()

    # ---------- 状态 ----------

    @property
    def pending_approval_ids(self) -> list[str]:
        """当前等待确认的审批 id。

        放进快照是为了让前端刷新页面后仍能发现"有条命令在等我点确认"，
        否则用户一切页面就再也看不到那个弹窗，任务会一直卡到超时。
        """
        with self._lock:
            return list(self._approvals)

    def snapshot(self) -> dict:
        usage = getattr(self.result, "usage", None)
        return {
            "task_id": self.id,
            "task": self.task,
            "status": self.status,
            "events": len(self._events),
            "pending_approvals": self.pending_approval_ids,
            "iterations": getattr(self.result, "iterations", None),
            "tokens": getattr(usage, "total_tokens", None),
            "text": getattr(self.result, "text", None),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    # ---------- 控制 ----------

    def request_stop(self) -> None:
        """中断。顺带放掉所有等待中的审批，否则 worker 会一直卡在 gate 上。"""
        self._stop.set()
        with self._lock:
            pending = list(self._approvals.values())
        for approval in pending:
            approval.approved = False
            approval.gate.set()

    def resolve_approval(self, approval_id: str, approved: bool) -> bool:
        with self._lock:
            approval = self._approvals.get(approval_id)
        if approval is None:
            return False
        approval.approved = approved
        approval.gate.set()
        return True

    # ---------- 供主循环调用的钩子 ----------

    def publish(self, event: AgentEvent) -> None:
        """worker 线程调用：只追加到缓冲，由订阅方按游标自行取走。"""
        with self._lock:
            self._events.append(event)

    def request_approval(self, command: str) -> bool:
        approval_id = uuid.uuid4().hex[:12]
        approval = _PendingApproval()
        with self._lock:
            self._approvals[approval_id] = approval

        self.publish(
            AgentEvent(
                type="approval_required",
                data={"approval_id": approval_id, "command": command},
            )
        )

        answered = approval.gate.wait(timeout=self._approval_timeout)
        with self._lock:
            self._approvals.pop(approval_id, None)

        if not answered:
            self.publish(
                AgentEvent(
                    type="approval_timeout",
                    data={"approval_id": approval_id, "command": command},
                )
            )
            return False
        return approval.approved

    def should_stop(self) -> bool:
        return self._stop.is_set()

    # ---------- 内部 ----------

    def _finish(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.finished_at = time.time()

    def _run(self) -> None:
        self.status = "running"
        try:
            agent = self._build_agent(self.request_approval, self.publish, self.should_stop)
            result = agent.run(self.task)
            self.result = result
        except Exception as exc:  # 任何意外都要落到会话状态里，不能只留在日志
            self.publish(AgentEvent(type="error", data={"message": f"{type(exc).__name__}: {exc}"}))
            self._finish("error")
            return
        self._finish("stopped" if self._stop.is_set() else result.stop_reason)


class SessionManager:
    """会话登记处。限制保留数量，避免长跑进程里会话无限堆积。"""

    def __init__(self, build_agent: AgentBuilder, approval_timeout: int = 300, max_sessions: int = 50):
        self._build_agent = build_agent
        self._approval_timeout = approval_timeout
        self._max_sessions = max_sessions
        self._sessions: dict[str, TaskSession] = {}
        self._lock = threading.Lock()

    def create(self, task: str) -> TaskSession:
        session = TaskSession(
            task=task,
            build_agent=self._build_agent,
            approval_timeout=self._approval_timeout,
        )
        with self._lock:
            self._sessions[session.id] = session
            self._evict_locked()
        session.start()
        return session

    def get(self, task_id: str) -> TaskSession | None:
        with self._lock:
            return self._sessions.get(task_id)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _evict_locked(self) -> None:
        """先淘汰已结束的；都还在跑就淘汰最旧的并中断它，避免线程泄漏。"""
        while len(self._sessions) > self._max_sessions:
            victim_id = next(
                (sid for sid, s in self._sessions.items() if s.finished),
                next(iter(self._sessions)),
            )
            victim = self._sessions.pop(victim_id)
            victim.request_stop()
