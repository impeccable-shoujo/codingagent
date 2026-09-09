"""会话落盘：每轮事件写成 jsonl。

成本几乎为零，但没它的时候 agent 行为诡异你只能靠猜。
后续传输层可以直接回放这些文件来复现 bug。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .types import AgentEvent


class RunLogger:
    def __init__(self, directory: Path | str = "runs", filename: str | None = None) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.dir / (filename or f"run-{stamp}.jsonl")
        self._fh = self.path.open("a", encoding="utf-8")

    def emit(self, event: AgentEvent) -> None:
        self._fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        self._fh.flush()

    def meta(self, **kwargs: Any) -> None:
        self.emit(AgentEvent(type="meta", data=kwargs))

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class NullLogger:
    """日志关闭时的空实现，让调用方不必到处判空。"""

    path: Path | None = None

    def emit(self, event: AgentEvent) -> None:
        return None

    def meta(self, **kwargs: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "NullLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        return None
