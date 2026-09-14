"""FastAPI 传输层：把 Agent 核心暴露成 HTTP + SSE 接口。

上行走 REST，下行走 SSE：
    POST /tasks             提交任务，立即返回 task_id（任务在后台线程跑）
    GET  /stream?task_id=   订阅事件流（SSE），先补历史再推实时
    POST /approve           批准或拒绝一次危险命令
    POST /stop              中断任务
    GET  /tasks/{task_id}   状态快照
    GET  /health            健康检查

这一层只做"搬运和编排"，不碰 Agent 核心的任何逻辑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..app import build_agent, build_provider
from ..config import DEFAULT_ENV_FILE, ConfigError, Settings
from ..provider import ProviderError
from ..types import AgentEvent
from .session import SessionManager, TaskSession

SSE_HEARTBEAT_SECONDS = 15


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000, description="自然语言任务描述")


class TaskCreated(BaseModel):
    task_id: str
    status: str


class ApprovalRequest(BaseModel):
    task_id: str
    approval_id: str
    approved: bool


class StopRequest(BaseModel):
    task_id: str


class OkResponse(BaseModel):
    ok: bool = True
    status: str | None = None


# SSE 拉取间隔。会话不绑定事件循环，靠轮询游标取事件，这里控制最大延迟。
SSE_POLL_SECONDS = 0.05


def format_sse(event: AgentEvent) -> str:
    """SSE 帧格式：event 行给类型、data 行给 JSON 负载，空行结束一帧。

    data 必须单行且不含裸换行，所以 JSON 里不能出现真实换行——
    json.dumps 默认会把换行转义成 \\n，正好满足要求。
    """
    payload = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"event: {event.type}\ndata: {payload}\n\n"


def create_app(settings: Settings | None = None, provider_factory=None) -> FastAPI:
    settings = settings or Settings.from_env()
    provider_factory = provider_factory or build_provider

    # 启动时就构造 provider：缺 key / 依赖缺失会立刻暴露，而不是等第一个任务失败
    provider = provider_factory(settings)

    def agent_builder(approval, sink, should_stop):
        return build_agent(
            settings,
            approval=approval,
            sink=sink,
            should_stop=should_stop,
            provider=provider,
            with_log=True,
        )

    manager = SessionManager(
        build_agent=agent_builder,
        approval_timeout=settings.approval_timeout,
        max_sessions=settings.max_sessions,
    )

    app = FastAPI(
        title="coding agent",
        version=__version__,
        description="最小可用的 coding agent 传输层：REST 上行 + SSE 下行",
    )
    app.state.settings = settings
    app.state.manager = manager
    app.state.provider = provider

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def require_session(task_id: str) -> TaskSession:
        session = manager.get(task_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"未知任务：{task_id}")
        return session

    @app.get("/")
    async def index() -> dict:
        return {
            "name": "coding agent",
            "version": __version__,
            "model": settings.model,
            "endpoints": {
                "POST /tasks": "提交任务，返回 task_id",
                "GET /stream?task_id=": "订阅事件流（SSE）",
                "POST /approve": "批准或拒绝危险命令",
                "POST /stop": "中断任务",
                "GET /tasks/{task_id}": "状态快照",
            },
        }

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "model": settings.model,
            # 每次请求重算：开启按日期归档后，跨零点这里要跟着变
            "workspace": str(settings.effective_workspace().resolve()),
            "sessions": manager.count(),
        }

    @app.post("/tasks", response_model=TaskCreated, status_code=202)
    async def create_task(body: TaskRequest) -> TaskCreated:
        """工作区来自服务端配置，不接受客户端指定——否则等于开放任意路径读写。"""
        session = manager.create(body.task)
        return TaskCreated(task_id=session.id, status=session.status)

    @app.get("/stream")
    async def stream(
        task_id: str = Query(..., description="任务 id"),
        cursor: int = Query(0, ge=0, description="从第几个事件开始，断线重连时传上次的游标"),
    ) -> StreamingResponse:
        session = require_session(task_id)
        start = session.subscribe(cursor)

        async def event_source():
            position = start
            idle = 0.0
            while True:
                events, position, finished = session.drain(position)
                for event in events:
                    yield format_sse(event)
                if finished:
                    return
                if events:
                    idle = 0.0
                else:
                    idle += SSE_POLL_SECONDS
                    if idle >= SSE_HEARTBEAT_SECONDS:
                        # 注释帧当心跳，防止中间层判定连接空闲而掐断
                        idle = 0.0
                        yield ": ping\n\n"
                await asyncio.sleep(SSE_POLL_SECONDS)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/approve", response_model=OkResponse)
    async def approve(body: ApprovalRequest) -> OkResponse:
        session = require_session(body.task_id)
        if not session.resolve_approval(body.approval_id, body.approved):
            raise HTTPException(status_code=404, detail="审批请求不存在或已失效")
        return OkResponse()

    @app.post("/stop", response_model=OkResponse)
    async def stop(body: StopRequest) -> OkResponse:
        session = require_session(body.task_id)
        session.request_stop()
        return OkResponse(status=session.status)

    @app.get("/tasks/{task_id}")
    async def task_detail(task_id: str) -> dict:
        return require_session(task_id).snapshot()

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-server", description="启动 coding agent 的 HTTP 传输层"
    )
    parser.add_argument("--env-file", default=None, help=f".env 文件路径，默认 {DEFAULT_ENV_FILE}")
    parser.add_argument("--host", default=None, help="覆盖监听地址")
    parser.add_argument("--port", type=int, default=None, help="覆盖监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重载")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env(env_file=args.env_file or DEFAULT_ENV_FILE)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    if args.host:
        settings = _with(settings, host=args.host)
    if args.port:
        settings = _with(settings, port=args.port)

    try:
        app = create_app(settings)
    except ProviderError as exc:
        print(f"无法初始化模型：{exc}", file=sys.stderr)
        print("提示：把密钥写进 .env 的 AGENT_API_KEY，或设置环境变量 ZHIPU_API_KEY。",
              file=sys.stderr)
        return 1

    import uvicorn

    print(f"coding agent 传输层启动中： http://{settings.host}:{settings.port}  （模型 {settings.model}）")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0


def _with(settings: Settings, **overrides) -> Settings:
    from dataclasses import replace

    return replace(settings, **overrides)


if __name__ == "__main__":
    raise SystemExit(main())
