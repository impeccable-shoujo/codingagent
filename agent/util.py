"""跨模块的小工具函数。"""

from __future__ import annotations

import sys
from pathlib import Path


def interpreter_path_dirs() -> list[Path]:
    """返回当前解释器所在环境里应加入 PATH 的目录。

    为什么需要这个：agent 用 bash 工具执行 `python -m pytest` 时，子进程看的是
    父进程的 PATH，而不是"父进程用的是哪个解释器"。如果 agent 跑在项目虚拟环境里，
    但 PATH 上没有这个环境，子进程就会落到别的 Python 上，报出莫名其妙的
    "No module named pytest"。把环境目录 prepend 上去，子进程才和 agent 同源。

    Windows 上可执行脚本在 <env>/Scripts，POSIX 上就在 <env>/bin（即解释器所在目录）。
    """
    root = Path(sys.executable).resolve().parent
    dirs = [root]
    scripts = root / "Scripts"  # Windows 的 pip 安装的 .exe 入口
    if scripts.is_dir():
        dirs.append(scripts)
    return dirs


def decode_output(data: bytes) -> str:
    """把命令/文件字节流解码成文本。

    Windows 中文环境下子进程输出常是 GBK，直接按 utf-8 解码要么报错要么乱码，
    所以先试 utf-8，失败再退回 GBK。
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")
