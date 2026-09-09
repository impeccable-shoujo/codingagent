"""跨模块的小工具函数。"""

from __future__ import annotations


def decode_output(data: bytes) -> str:
    """把命令/文件字节流解码成文本。

    Windows 中文环境下子进程输出常是 GBK，直接按 utf-8 解码要么报错要么乱码，
    所以先试 utf-8，失败再退回 GBK。
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")
