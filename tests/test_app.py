"""组装与 CLI 测试：验证配置真的接到了 agent 上，而不是只存在于文件里。"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from agent.app import build_agent
from agent.config import Settings
from agent.provider import ProviderError
from agent.repl import _apply_cli_overrides, build_parser, main


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(api_key="sk-test-key-1234", workspace=tmp_path, log_dir=tmp_path / "logs")
    base.update(overrides)
    return Settings(**base)


def test_settings_reach_the_loop(tmp_path):
    settings = make_settings(tmp_path, max_iterations=5, max_consecutive_failures=2)
    loop = build_agent(settings, with_log=False)

    assert loop.config.max_iterations == 5
    assert loop.config.max_consecutive_failures == 2
    assert len(loop.tools) == 3


def test_workspace_from_settings_is_used(tmp_path):
    loop = build_agent(make_settings(tmp_path), with_log=False)

    result = loop.tools.get("write_file").fn({"path": "a.txt", "content": "v"})

    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v"


def test_default_approval_denies_ask_commands(tmp_path):
    """没打开 auto_approve 时，需要确认的命令必须被拒——这是安全默认值。"""
    loop = build_agent(make_settings(tmp_path), with_log=False)

    result = loop.tools.get("bash").fn({"command": "rm hello.txt"})

    assert not result.ok
    assert "未获批准" in result.error


def test_auto_approve_allows_ask_commands(tmp_path):
    loop = build_agent(make_settings(tmp_path, auto_approve=True), with_log=False)

    result = loop.tools.get("bash").fn({"command": "echo approved"})

    assert result.ok


def test_auto_approve_still_blocks_hard_denied_commands(tmp_path):
    """两级安全是独立的：自动批准只放开 ASK，不能越过 DENY。"""
    loop = build_agent(make_settings(tmp_path, auto_approve=True), with_log=False)

    result = loop.tools.get("bash").fn({"command": "sudo echo pwned"})

    assert not result.ok
    assert "已拦截" in result.error


def test_output_limits_from_settings_are_applied(tmp_path):
    """截断阈值必须来自配置，否则长输出会撑爆上下文。"""
    settings = make_settings(tmp_path, max_output_lines=5, max_output_chars=10_000)
    loop = build_agent(settings, with_log=False)

    loop.tools.get("write_file").fn(
        {"path": "big.txt", "content": "\n".join(f"line{i}" for i in range(200))}
    )
    result = loop.tools.get("read_file").fn({"path": "big.txt"})

    assert result.ok
    assert result.truncated
    assert "已省略" in result.output


def test_workspace_directory_is_created_by_assembly(tmp_path):
    """工作区可能还不存在（按日期归档时就会这样），装配阶段负责建好。"""
    target = tmp_path / "not-yet" / "deeper"
    settings = make_settings(tmp_path, workspace=target, dated_output=True)

    build_agent(settings, with_log=False)

    assert (target / date.today().isoformat()).is_dir()


def test_dated_output_lands_in_today_folder(tmp_path):
    loop = build_agent(make_settings(tmp_path, dated_output=True), with_log=False)

    result = loop.tools.get("write_file").fn({"path": "a.txt", "content": "v"})

    assert result.ok
    today_dir = tmp_path / date.today().isoformat()
    assert (today_dir / "a.txt").read_text(encoding="utf-8") == "v"
    assert not (tmp_path / "a.txt").exists(), "不该落在工作区根目录"


def test_dated_output_confines_writes_to_today(tmp_path):
    """昨天/明天的目录在沙箱之外，写不进去——归档靠沙箱强制，不靠模型自觉。"""
    other_day = (date.today() - timedelta(days=1)).isoformat()
    (tmp_path / other_day).mkdir()
    loop = build_agent(make_settings(tmp_path, dated_output=True), with_log=False)

    result = loop.tools.get("write_file").fn({"path": f"../{other_day}/x.txt", "content": "v"})

    assert not result.ok
    assert "越界" in result.error
    assert not (tmp_path / other_day / "x.txt").exists()


def test_dated_output_reads_today_folder(tmp_path):
    """读也要在同一目录内，否则归档只剩一半。"""
    today_dir = tmp_path / date.today().isoformat()
    today_dir.mkdir()
    (today_dir / "note.txt").write_text("今天的内容", encoding="utf-8")
    loop = build_agent(make_settings(tmp_path, dated_output=True), with_log=False)

    result = loop.tools.get("read_file").fn({"path": "note.txt"})

    assert result.ok
    assert "今天的内容" in result.output


def test_dated_output_off_uses_workspace_root(tmp_path):
    """关掉开关时行为与之前完全一致——老用户不受影响。"""
    loop = build_agent(make_settings(tmp_path), with_log=False)

    result = loop.tools.get("write_file").fn({"path": "a.txt", "content": "v"})

    assert result.ok
    assert (tmp_path / "a.txt").exists()


def test_missing_api_key_raises_provider_error(tmp_path):
    with pytest.raises(ProviderError, match="API Key"):
        build_agent(make_settings(tmp_path, api_key=None), with_log=False)


def test_logger_created_when_enabled(tmp_path):
    loop = build_agent(make_settings(tmp_path), with_log=True)
    try:
        assert loop.logger.path is not None
        assert Path(loop.logger.path).parent == tmp_path / "logs"
    finally:
        loop.logger.close()


def test_no_log_uses_null_logger(tmp_path):
    loop = build_agent(make_settings(tmp_path), with_log=False)
    assert loop.logger.path is None


# ---------- CLI 与配置的优先级 ----------


def test_cli_defaults_are_none_so_env_can_win():
    """命令行默认值必须是 None，否则 .env 里的配置永远不生效。"""
    args = build_parser().parse_args([])
    assert args.model is None
    assert args.workspace is None
    assert args.max_iterations is None
    assert args.log_dir is None
    assert args.base_url is None


def test_cli_overrides_beat_env(tmp_path):
    settings = Settings.from_env(env={"AGENT_MODEL": "from-env"}, env_file=tmp_path / "x.env")
    args = build_parser().parse_args(["-m", "from-cli", "--max-iterations", "3"])

    merged = _apply_cli_overrides(settings, args)

    assert merged.model == "from-cli"
    assert merged.max_iterations == 3


def test_cli_leaves_unset_values_untouched(tmp_path):
    settings = Settings.from_env(env={"AGENT_MODEL": "from-env"}, env_file=tmp_path / "x.env")

    merged = _apply_cli_overrides(settings, build_parser().parse_args(["-q"]))

    assert merged == settings


def test_yes_flag_enables_auto_approve(tmp_path):
    settings = Settings.from_env(env={}, env_file=tmp_path / "x.env")
    merged = _apply_cli_overrides(settings, build_parser().parse_args(["-y"]))
    assert merged.auto_approve is True


def test_show_config_prints_and_masks_secret(tmp_path, capsys, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AGENT_API_KEY=sk-verysecretvalue1234\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_API_KEY", "sk-verysecretvalue1234")

    code = main(["--show-config", "--env-file", str(env_file)])
    out = capsys.readouterr().out

    assert code == 0
    assert "verysecretvalue" not in out
    assert "当前生效配置" in out


def test_bad_config_exits_with_clear_error(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("AGENT_MAX_ITERATIONS=abc\n", encoding="utf-8")

    code = main(["--show-config", "--env-file", str(env_file)])
    err = capsys.readouterr().err

    assert code == 1
    assert "配置错误" in err
