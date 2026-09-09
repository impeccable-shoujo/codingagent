"""read_file：带行号读取文件，支持分段读取。

带行号是关键设计：模型靠行号定位代码，也靠行号表达"改这里"，
后面如果要加 edit 工具，行号就是两者的共同语言。
"""

from __future__ import annotations

from ..util import decode_output
from .base import Tool, ToolContext, ToolResult, resolve_in_workspace, truncate_output

PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径，相对工作区"},
        "offset": {"type": "integer", "description": "起始行号，从 1 开始，默认 1"},
        "limit": {"type": "integer", "description": "最多读取多少行，默认读到文件末尾"},
    },
    "required": ["path"],
}


def build_read_file_tool(ctx: ToolContext) -> Tool:
    def _read(args: dict) -> ToolResult:
        raw = args.get("path")
        if not raw:
            return ToolResult(ok=False, error="缺少参数 path")

        try:
            path = resolve_in_workspace(ctx.workspace, str(raw))
        except Exception as exc:  # ToolError
            return ToolResult(ok=False, error=str(exc))

        if not path.exists():
            return ToolResult(ok=False, error=f"文件不存在：{raw}")
        if path.is_dir():
            return ToolResult(ok=False, error=f"{raw} 是目录，不是文件")

        try:
            text = decode_output(path.read_bytes())
        except OSError as exc:
            return ToolResult(ok=False, error=f"读取失败：{exc}")

        lines = text.splitlines()
        total = len(lines)
        start = max(1, int(args.get("offset") or 1))
        limit = int(args.get("limit") or 0)
        end = total if limit <= 0 else min(total, start + limit - 1)

        selected = lines[start - 1 : end] if start <= total else []
        body = "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(selected, start=start))
        body, truncated = truncate_output(body, ctx.max_chars, ctx.max_lines)

        header = f"# {raw}（共 {total} 行，显示 {start}-{end}）"
        if truncated:
            header += " [输出已截断]"
        return ToolResult(ok=True, output=f"{header}\n{body}", truncated=truncated)

    return Tool(
        name="read_file",
        description="读取工作区内的文件内容，带行号。可用 offset/limit 分段读取大文件。",
        parameters=PARAMETERS,
        fn=_read,
    )
