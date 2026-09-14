"""配置层测试：优先级、类型校验、密钥解析、以及"不污染进程环境"。"""

import dataclasses
import os
from datetime import date
from pathlib import Path

import pytest

from agent.config import (
    DEFAULT_MODEL,
    ConfigError,
    Settings,
    describe,
    load_env_file,
    mask_secret,
)


def write_env(tmp_path, content: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_when_nothing_configured(tmp_path):
    settings = Settings.from_env(env={}, env_file=tmp_path / "missing.env")
    # 断言引用常量本身，换模型时不需要改测试
    assert settings.model == DEFAULT_MODEL
    assert DEFAULT_MODEL
    assert settings.max_iterations == 25
    assert settings.max_consecutive_failures == 3
    assert settings.auto_approve is False
    assert settings.api_key is None
    assert settings.workspace == Path(".")


def test_env_file_is_loaded(tmp_path):
    env_file = write_env(tmp_path, "AGENT_MODEL=deepseek-chat\nAGENT_MAX_ITERATIONS=7\n")
    settings = Settings.from_env(env={}, env_file=env_file)
    assert settings.model == "deepseek-chat"
    assert settings.max_iterations == 7


def test_real_env_overrides_env_file(tmp_path):
    """CI / 临时覆盖必须压过仓库里的 .env，否则线上行为会被本地文件改掉。"""
    env_file = write_env(tmp_path, "AGENT_MODEL=from-file\n")
    settings = Settings.from_env(env={"AGENT_MODEL": "from-env"}, env_file=env_file)
    assert settings.model == "from-env"


def test_quoted_values_are_unwrapped(tmp_path):
    env_file = write_env(tmp_path, 'AGENT_MODEL="glm-4.5-air"\n')
    assert Settings.from_env(env={}, env_file=env_file).model == "glm-4.5-air"


def test_env_file_with_comments_and_blank_lines(tmp_path):
    env_file = write_env(tmp_path, "# 注释\n\nAGENT_MODEL=m1\n\n# 又一行注释\n")
    assert Settings.from_env(env={}, env_file=env_file).model == "m1"


def test_api_key_read_directly_from_env_file(tmp_path):
    env_file = write_env(tmp_path, "AGENT_API_KEY=sk-abcdef123456\n")
    assert Settings.from_env(env={}, env_file=env_file).api_key == "sk-abcdef123456"


def test_api_key_resolved_indirectly_via_key_env(tmp_path):
    env_file = write_env(tmp_path, "AGENT_API_KEY_ENV=MY_CUSTOM_KEY\n")
    settings = Settings.from_env(env={"MY_CUSTOM_KEY": "sk-indirect"}, env_file=env_file)
    assert settings.api_key == "sk-indirect"


def test_direct_api_key_beats_indirect(tmp_path):
    env_file = write_env(tmp_path, "AGENT_API_KEY_ENV=MY_CUSTOM_KEY\nAGENT_API_KEY=sk-direct\n")
    settings = Settings.from_env(env={"MY_CUSTOM_KEY": "sk-indirect"}, env_file=env_file)
    assert settings.api_key == "sk-direct"


def test_reading_config_does_not_pollute_os_environ(tmp_path, monkeypatch):
    """配置读取必须无全局副作用，否则测试之间会互相污染。"""
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    env_file = write_env(tmp_path, "AGENT_MODEL=leaked-into-environ\n")
    Settings.from_env(env={}, env_file=env_file)
    assert "AGENT_MODEL" not in os.environ


def test_empty_value_falls_back_to_default(tmp_path):
    env_file = write_env(tmp_path, "AGENT_MAX_ITERATIONS=\nAGENT_API_KEY=\n")
    settings = Settings.from_env(env={}, env_file=env_file)
    assert settings.max_iterations == 25
    assert settings.api_key is None


@pytest.mark.parametrize("value", ["abc", "1.5", "十"])
def test_invalid_int_raises(tmp_path, value):
    env_file = write_env(tmp_path, f"AGENT_MAX_ITERATIONS={value}\n")
    with pytest.raises(ConfigError, match="必须是整数"):
        Settings.from_env(env={}, env_file=env_file)


@pytest.mark.parametrize(
    "line,match",
    [
        ("AGENT_MAX_ITERATIONS=0", "必须 >= 1"),
        ("AGENT_MAX_OUTPUT_CHARS=10", "必须 >= 100"),
        ("AGENT_COMMAND_TIMEOUT=0", "必须 >= 1"),
    ],
)
def test_out_of_range_int_raises(tmp_path, line, match):
    env_file = write_env(tmp_path, line + "\n")
    with pytest.raises(ConfigError, match=match):
        Settings.from_env(env={}, env_file=env_file)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ],
)
def test_bool_parsing(tmp_path, raw, expected):
    env_file = write_env(tmp_path, f"AGENT_AUTO_APPROVE={raw}\n")
    assert Settings.from_env(env={}, env_file=env_file).auto_approve is expected


def test_invalid_bool_raises(tmp_path):
    env_file = write_env(tmp_path, "AGENT_AUTO_APPROVE=maybe\n")
    with pytest.raises(ConfigError, match="必须是布尔值"):
        Settings.from_env(env={}, env_file=env_file)


def test_negative_temperature_is_allowed(tmp_path):
    env_file = write_env(tmp_path, "AGENT_TEMPERATURE=0.2\n")
    assert Settings.from_env(env={}, env_file=env_file).temperature == pytest.approx(0.2)


def test_settings_is_immutable(tmp_path):
    settings = Settings.from_env(env={}, env_file=tmp_path / "x.env")
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.model = "other"  # type: ignore[misc]


def test_describe_masks_api_key(tmp_path):
    env_file = write_env(tmp_path, "AGENT_API_KEY=sk-verysecretvalue1234\n")
    text = describe(Settings.from_env(env={}, env_file=env_file))
    assert "verysecretvalue" not in text
    assert "sk-v" in text


def test_mask_secret_edge_cases():
    assert mask_secret(None) == "(未设置)"
    assert mask_secret("short") == "*****"
    assert mask_secret("sk-1234567890ab") == "sk-1...90ab"


def test_load_env_file_missing_returns_empty(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == {}
    assert load_env_file(None) == {}


def test_shipped_env_example_is_valid_and_documents_all_keys():
    """.env.example 必须能被解析，且覆盖所有受支持的配置项。"""
    example = Path(__file__).resolve().parent.parent / ".env.example"
    values = load_env_file(example)
    expected_keys = {
        "AGENT_MODEL",
        "AGENT_BASE_URL",
        "AGENT_TEMPERATURE",
        "AGENT_API_KEY",
        "AGENT_API_KEY_ENV",
        "AGENT_MAX_ITERATIONS",
        "AGENT_MAX_CONSECUTIVE_FAILURES",
        "AGENT_COMMAND_TIMEOUT",
        "AGENT_MAX_OUTPUT_CHARS",
        "AGENT_MAX_OUTPUT_LINES",
        "AGENT_WORKSPACE",
        "AGENT_DATED_OUTPUT",
        "AGENT_LOG_DIR",
        "AGENT_AUTO_APPROVE",
        "AGENT_HOST",
        "AGENT_PORT",
        "AGENT_APPROVAL_TIMEOUT",
        "AGENT_CORS_ORIGINS",
        "AGENT_MAX_SESSIONS",
    }
    missing = expected_keys - set(values)
    assert not missing, f".env.example 缺少配置项：{sorted(missing)}"


def test_cors_origins_parsed_as_list(tmp_path):
    env_file = write_env(tmp_path, "AGENT_CORS_ORIGINS=http://a.test, http://b.test\n")
    settings = Settings.from_env(env={}, env_file=env_file)
    assert settings.cors_origins == ("http://a.test", "http://b.test")


def test_blank_cors_origins_falls_back_to_default(tmp_path):
    env_file = write_env(tmp_path, "AGENT_CORS_ORIGINS=,,\n")
    assert Settings.from_env(env={}, env_file=env_file).cors_origins


def test_dated_output_defaults_to_off(tmp_path):
    """默认不归档：别人的仓库直接拿来用，不该被日期目录改变行为。"""
    settings = Settings.from_env(env={}, env_file=tmp_path / "missing.env")

    assert settings.dated_output is False
    assert settings.effective_workspace() == settings.workspace


def test_dated_output_can_be_enabled_from_env(tmp_path):
    env_file = write_env(tmp_path, "AGENT_DATED_OUTPUT=true\n")
    assert Settings.from_env(env={}, env_file=env_file).dated_output is True


def test_effective_workspace_appends_iso_date(tmp_path):
    settings = Settings(workspace=tmp_path, dated_output=True)

    assert settings.effective_workspace(date(2026, 9, 14)) == tmp_path / "2026-09-14"
    # 不传日期时用当天，ISO 格式便于排序
    assert settings.effective_workspace() == tmp_path / date.today().isoformat()


def test_effective_workspace_ignores_date_when_disabled(tmp_path):
    settings = Settings(workspace=tmp_path)
    assert settings.effective_workspace(date(2026, 9, 14)) == tmp_path


def test_describe_shows_effective_workspace_when_dated(tmp_path):
    settings = Settings(workspace=tmp_path, dated_output=True)
    text = describe(settings)
    assert date.today().isoformat() in text


def test_server_settings_have_defaults(tmp_path):
    settings = Settings.from_env(env={}, env_file=tmp_path / "missing.env")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.approval_timeout == 300
    assert settings.max_sessions == 50


def test_env_example_model_matches_code_default():
    """模板与代码默认值必须一致，否则新克隆的人会拿到一个和文档不符的模型。"""
    example = Path(__file__).resolve().parent.parent / ".env.example"
    values = load_env_file(example)
    assert values["AGENT_MODEL"] == DEFAULT_MODEL
