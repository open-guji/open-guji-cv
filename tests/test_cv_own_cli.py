"""cv 自己的命令行入口 `guji-cv`（2026-11-22 用户定）：只有 cv 的命令；大步工具可写前缀 `guji-cv <大步> <命令>`。"""
import argparse

import pytest

from open_guji_cv import cli_v2


def _choices(plugins: bool) -> set[str]:
    sub = argparse.ArgumentParser().add_subparsers(dest="command")
    cli_v2.register_subcommands(sub, plugins=plugins)
    return set(sub.choices)


def test_stage_commands_are_real_cv_commands():
    cv = _choices(plugins=False)
    for stage, cmds in cli_v2.STAGE_COMMANDS.items():
        assert stage not in cv            # 大步名不能和命令撞名
        assert set(cmds) <= cv, stage


def test_strip_stage_prefix():
    s = cli_v2.strip_stage_prefix
    assert s(["layout", "preclean", "vol04", "-w", "x"]) == ["preclean", "vol04", "-w", "x"]
    assert s(["read", "rare", "vol04"]) == ["rare", "vol04"]
    assert s(["preclean", "vol04"]) == ["preclean", "vol04"]         # 不带前缀照样认
    assert s(["status", "vol04"]) == ["status", "vol04"]
    with pytest.raises(SystemExit, match="不属于大步 layout"):
        s(["layout", "rare", "vol04"])
    with pytest.raises(SystemExit, match="guji-cv cut 下的命令"):
        s(["cut"])


def test_cv_main_help_lists_only_cv(capsys):
    with pytest.raises(SystemExit):
        cli_v2.cv_main(["--help"])
    out = capsys.readouterr().out
    assert "guji-cv" in out and "pipeline" in out
