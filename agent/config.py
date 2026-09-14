"""统一配置：所有可变参数集中在这里，从环境变量 / .env 读取。

优先级（高到低）：
    命令行参数 > 真实环境变量 > .env 文件 > 代码默认值

真实环境变量之所以要压过 .env，是为了让 CI、临时覆盖、容器注入不被仓库里的
文件悄悄盖掉——这个顺序反了会非常难查。

设计取舍：不修改 os.environ。dotenv 常见的做法是把值灌进进程环境，
但那会让测试相互污染、也让配置来源变得不可见。这里只返回一个不可变对象，
谁需要什么就显式传进去。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values

ENV_PREFIX = "AGENT_"
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_API_KEY_ENV = "ZHIPU_API_KEY"
DEFAULT_MODEL = "glm-4.5-air"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


class ConfigError(ValueError):
    """配置项非法。直接报错而不是悄悄用默认值——静默降级比报错更难排查。"""


def load_env_file(env_file: Path | str | None = DEFAULT_ENV_FILE) -> dict[str, str]:
    """读取 .env，返回键值对；文件不存在时返回空 dict。"""
    if env_file is None:
        return {}
    path = Path(env_file)
    if not path.is_file():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def _lookup(merged: Mapping[str, Any], name: str) -> str | None:
    value = merged.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prefixed(merged: Mapping[str, Any], key: str) -> str | None:
    return _lookup(merged, ENV_PREFIX + key)


def _as_str(merged: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    text = _prefixed(merged, key)
    return text if text is not None else default


def _as_int(
    merged: Mapping[str, Any], key: str, default: int, minimum: int | None = None
) -> int:
    text = _prefixed(merged, key)
    if text is None:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ConfigError(f"{ENV_PREFIX}{key} 必须是整数，当前是 {text!r}") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{ENV_PREFIX}{key} 必须 >= {minimum}，当前是 {value}")
    return value


def _as_float(merged: Mapping[str, Any], key: str, default: float) -> float:
    text = _prefixed(merged, key)
    if text is None:
        return default
    try:
        return float(text)
    except ValueError:
        raise ConfigError(f"{ENV_PREFIX}{key} 必须是数字，当前是 {text!r}") from None


def _as_bool(merged: Mapping[str, Any], key: str, default: bool) -> bool:
    text = _prefixed(merged, key)
    if text is None:
        return default
    lowered = text.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(
        f"{ENV_PREFIX}{key} 必须是布尔值（true/false/1/0），当前是 {text!r}"
    )


def _as_list(merged: Mapping[str, Any], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    text = _prefixed(merged, key)
    if text is None:
        return default
    items = tuple(part.strip() for part in text.split(",") if part.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    """运行期配置。frozen 是刻意的：配置在启动后不应该被任何代码悄悄改掉。"""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    temperature: float = 0.0
    workspace: Path = Path(".")
    # 产出按日期归档：工作区自动落到 <workspace>/<YYYY-MM-DD>/ 下
    dated_output: bool = False
    max_iterations: int = 25
    max_consecutive_failures: int = 3
    max_output_chars: int = 10_000
    max_output_lines: int = 200
    command_timeout: int = 60
    log_dir: Path = Path("runs")
    auto_approve: bool = False
    env_file: Path | None = None

    # ---------- HTTP 传输层 ----------
    host: str = "127.0.0.1"
    port: int = 8000
    # 危险命令等待用户点确认的最长时间，超时按拒绝处理
    approval_timeout: int = 300
    # 允许的前端来源。默认放行 Vite 开发服务器，方便 v0.3 接前端
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    # 内存中保留的会话数上限，避免长跑进程无限增长
    max_sessions: int = 50

    def effective_workspace(self, today: date | None = None) -> Path:
        """实际生效的工作区。

        打开 dated_output 后，工作区落到 <workspace>/<YYYY-MM-DD>/。
        关键在于"产出归到当天文件夹"这件事由**工作区沙箱**保证，而不是靠提示词
        请模型自觉：工具层的越界检查会把写入拦在当天目录内，模型就算想写别处也写不进去。
        靠提示词的方案一旦模型不听话就会静默失效。

        代价是拿不到其它日期的文件——需要跨天接续工作时把这个开关关掉即可。
        """
        root = Path(self.workspace)
        if not self.dated_output:
            return root
        return root / (today or date.today()).isoformat()

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        env_file: Path | str | None = DEFAULT_ENV_FILE,
    ) -> "Settings":
        import os

        file_values = load_env_file(env_file)
        environ = dict(os.environ) if env is None else dict(env)
        merged: dict[str, Any] = {**file_values, **environ}

        api_key = _as_str(merged, "API_KEY")
        if not api_key:
            key_var = _as_str(merged, "API_KEY_ENV", DEFAULT_API_KEY_ENV) or DEFAULT_API_KEY_ENV
            api_key = _lookup(merged, key_var)

        return cls(
            model=_as_str(merged, "MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            base_url=_as_str(merged, "BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            api_key=api_key,
            temperature=_as_float(merged, "TEMPERATURE", 0.0),
            workspace=Path(_as_str(merged, "WORKSPACE", ".") or "."),
            dated_output=_as_bool(merged, "DATED_OUTPUT", False),
            max_iterations=_as_int(merged, "MAX_ITERATIONS", 25, minimum=1),
            max_consecutive_failures=_as_int(merged, "MAX_CONSECUTIVE_FAILURES", 3, minimum=1),
            max_output_chars=_as_int(merged, "MAX_OUTPUT_CHARS", 10_000, minimum=100),
            max_output_lines=_as_int(merged, "MAX_OUTPUT_LINES", 200, minimum=1),
            command_timeout=_as_int(merged, "COMMAND_TIMEOUT", 60, minimum=1),
            log_dir=Path(_as_str(merged, "LOG_DIR", "runs") or "runs"),
            auto_approve=_as_bool(merged, "AUTO_APPROVE", False),
            env_file=Path(env_file) if env_file else None,
            host=_as_str(merged, "HOST", "127.0.0.1") or "127.0.0.1",
            port=_as_int(merged, "PORT", 8000, minimum=1),
            approval_timeout=_as_int(merged, "APPROVAL_TIMEOUT", 300, minimum=1),
            cors_origins=_as_list(
                merged,
                "CORS_ORIGINS",
                ("http://localhost:5173", "http://127.0.0.1:5173"),
            ),
            max_sessions=_as_int(merged, "MAX_SESSIONS", 50, minimum=1),
        )


def mask_secret(secret: str | None) -> str:
    """日志和终端里只显示密钥的尾巴，避免被截图或贴进 issue。"""
    if not secret:
        return "(未设置)"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def describe(settings: Settings) -> str:
    """打印生效配置，用于排查"为什么参数没起作用"。"""
    lines = [
        "当前生效配置：",
        f"  .env 文件     {settings.env_file if settings.env_file else '(未使用)'}"
        + ("" if settings.env_file and Path(settings.env_file).is_file() else "  [文件不存在]"),
        f"  模型          {settings.model}",
        f"  端点          {settings.base_url}",
        f"  密钥          {mask_secret(settings.api_key)}",
        f"  温度          {settings.temperature}",
        f"  工作区        {Path(settings.workspace).resolve()}",
        f"  按日期归档    {'是 → ' + str(settings.effective_workspace().resolve()) if settings.dated_output else '否'}",
        f"  最大迭代      {settings.max_iterations}",
        f"  连续失败熔断  {settings.max_consecutive_failures}",
        f"  命令超时      {settings.command_timeout}s",
        f"  输出截断      {settings.max_output_chars} 字符 / {settings.max_output_lines} 行",
        f"  日志目录      {settings.log_dir}",
        f"  自动批准      {settings.auto_approve}",
        f"  监听地址      http://{settings.host}:{settings.port}",
        f"  审批超时      {settings.approval_timeout}s",
        f"  允许来源      {', '.join(settings.cors_origins)}",
        f"  会话上限      {settings.max_sessions}",
    ]
    return "\n".join(lines)
