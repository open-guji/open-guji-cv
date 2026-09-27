"""CLI 带 book 的命令必填 `-w/--workspace`（2026-09-20，用户定）。

`GUJI_WORKSPACE` 环境变量漏设/设错都不报错：漏设时册定义找不到（好歹会炸），设错时
产物静默写到别的工作区。一天里两次栽在这上面之后改成显式参数：不给就在 argparse 层报错，
给了就校验目录里有这册书的定义，再写进环境变量供下游用。
"""

from __future__ import annotations

import argparse
import os

import pytest

from open_guji_cv import cli_v2


def _parser():
    parser = argparse.ArgumentParser(prog="guji")
    sub = parser.add_subparsers(dest="command")
    cli_v2.register_subcommands(sub)
    return parser


def test_book_commands_get_the_flag_and_others_do_not():
    parser = _parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert any(a.dest == "workspace" for a in sub.choices["pipeline"]._actions)
    assert any(a.dest == "workspace" for a in sub.choices["status"]._actions)
    assert not any(a.dest == "workspace" for a in sub.choices["console"]._actions)


def test_missing_workspace_is_a_parse_error(capsys):
    parser = _parser()
    args = parser.parse_args(["status", "bxgb"])
    with pytest.raises(SystemExit):
        cli_v2.COMMANDS_V2["status"](args)
    assert "--workspace" in capsys.readouterr().err


def test_workspace_without_book_yaml_is_rejected(tmp_path, capsys):
    parser = _parser()
    args = parser.parse_args(["status", "bxgb", "-w", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli_v2.resolve_workspace(args, parser)
    assert "books/bxgb.yaml" in capsys.readouterr().err


def test_valid_workspace_is_exported_to_env(tmp_path, monkeypatch):
    (tmp_path / "books").mkdir()
    (tmp_path / "books" / "bxgb.yaml").write_text("id: bxgb\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", "D:/somewhere/else")
    parser = _parser()
    args = parser.parse_args(["status", "bxgb", "--workspace", str(tmp_path)])
    root = cli_v2.resolve_workspace(args, parser)
    assert root == tmp_path.resolve()
    assert os.environ["GUJI_WORKSPACE"] == str(tmp_path.resolve())


def test_job_argv_carries_workspace():
    from open_guji_cv.console.jobs import JobSpec
    spec = JobSpec(pipeline="keben_body_v2", book="bxgb", pages="all", workspace="D:/ws")
    argv = spec.argv()
    assert "--workspace" in argv and argv[argv.index("--workspace") + 1] == "D:/ws"
