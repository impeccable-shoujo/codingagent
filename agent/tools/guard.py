"""命令安全守卫：把 bash 工具的能力关进笼子里。

分三档处理：
- DENY：无论如何都不执行（删根、提权、格式化、强制推送等）
- ASK：能力合法但后果不可逆，需要人类确认（删文件、git 写操作、装依赖）
- ALLOW：只读或低风险命令

为什么分三档而不是只做黑名单：全禁会让 agent 几乎干不了活，
全放行则一次 prompt 注入就能毁掉工作区。分级是为了在可用和安全之间取平衡。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class GuardAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class GuardDecision:
    action: GuardAction
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.action is GuardAction.ALLOW

    @property
    def needs_approval(self) -> bool:
        return self.action is GuardAction.ASK


# (正则, 说明)。命中即拒绝，不给模型任何绕过机会。
HARD_DENY_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-[rRfF]{1,3}\b[^\n]*\s(/\s*$|/\*|~/?\s*$|\.$|C:\\\s*$|D:\\\s*$)", "递归删除根目录或家目录"),
    (r"\bsudo\b", "禁止提权执行"),
    (r"\bmkfs\b", "禁止格式化磁盘"),
    (r"\bdd\s+if=", "禁止直接写块设备"),
    (r"\(\s*\)\s*\{[^}]*\|[^}]*&\s*\}", "禁止 fork 炸弹"),
    (r"\b(shutdown|reboot|init\s+0)\b", "禁止关机或重启"),
    (r"\bgit\s+push\b[^\n]*(-f\b|--force\b)", "禁止强制推送"),
    (r"\bchmod\s+-R\s+777\s+/", "禁止对根目录开放全权限"),
    (r">\s*/dev/(sd|nvme|hd)", "禁止直接写磁盘设备"),
    (r"\bcurl\b[^\n]*\|\s*(sudo\s+)?(ba|z|d)?sh\b", "禁止下载即执行"),
    (r"\bgit\s+reset\s+--hard\b", "禁止硬重置，会丢失未提交改动"),
    (r"\bgit\s+clean\s+-[fxd]", "禁止清理未跟踪文件"),
]

# 合法但需要人类点头的命令。
ASK_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\b", "删除文件"),
    (r"\brmdir\b", "删除目录"),
    (r"\bdel\s+/[sq]\b", "批量删除文件（Windows）"),
    (r"\bmv\b", "移动或重命名文件"),
    (r"\bgit\s+(commit|push|checkout|reset|rebase|merge|tag)\b", "会改动仓库状态的 git 操作"),
    (r"\bpip\s+install\b", "安装依赖"),
    (r"\bnpm\s+(install|ci)\b", "安装依赖"),
]


class CommandGuard:
    def __init__(
        self,
        extra_deny: list[tuple[str, str]] | None = None,
        extra_ask: list[tuple[str, str]] | None = None,
    ) -> None:
        self._deny = [
            (re.compile(p, re.IGNORECASE), why) for p, why in HARD_DENY_PATTERNS + (extra_deny or [])
        ]
        self._ask = [
            (re.compile(p, re.IGNORECASE), why) for p, why in ASK_PATTERNS + (extra_ask or [])
        ]

    def check(self, command: str) -> GuardDecision:
        normalized = " ".join(command.split())
        if not normalized:
            return GuardDecision(GuardAction.DENY, "空命令")

        for pattern, why in self._deny:
            if pattern.search(normalized):
                return GuardDecision(GuardAction.DENY, f"已拦截（{why}）：{normalized}")

        for pattern, why in self._ask:
            if pattern.search(normalized):
                return GuardDecision(GuardAction.ASK, f"需要确认（{why}）：{normalized}")

        return GuardDecision(GuardAction.ALLOW)
