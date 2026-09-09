"""write_file：全量覆盖写入文件。

MVP 阶段只做全量覆盖，不做 diff 补丁：全量写入最简单也最不容易出错，
代价是改大文件时更费 token。等真的被这个代价卡住了，再在 v0.2 加 edit 工具。
"""

from __future__ import annotations

from .base import Tool, ToolContext, ToolResult, resolve_in_workspace

PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径，相对工作区，父目录会自动创建"},
        "content": {"type": "string", "description": "文件完整内容，会整体覆盖原文件"},
    },
    "required": ["path", "content"],
}


def build_write_file_tool(ctx: ToolContext) -> Tool:
    def _write(args: dict) -> ToolResult:
        raw = args.get("path")
        content = args.get("content")
        if not raw:
            return ToolResult(ok=False, error="缺少参数 path")
        if content is None:
            return ToolResult(ok=False, error="缺少参数 content")

        try:
            path = resolve_in_workspace(ctx.workspace, str(raw))
        except Exception as exc:  # ToolError
            return ToolResult(ok=False, error=str(exc))

        if path.is_dir():
            return ToolResult(ok=False, error=f"{raw} 是目录，不能当作文件写入")

        try:
            existed = path.exists()
            before = decode_if_exists(path) if existed else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, error=f"写入失败：{exc}")

        if existed and before == content:
            return ToolResult(ok=True, output=f"{raw} 内容未变化，未做写入")
        action = "覆盖" if existed else "新建"
        return ToolResult(ok=True, output=f"已{action} {raw}（{len(content)} 字符）")

    return Tool(
        name="write_file",
        description="把完整内容写入工作区内的文件，父目录会自动创建。会覆盖原文件。",
        parameters=PARAMETERS,
        fn=_write,
    )


def decode_if_exists(path) -> str | None:
    from ..util import decode_output

    try:
        return decode_output(path.read_bytes())
    except OSError:
        return None
