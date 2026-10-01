# -*- coding: utf-8 -*-
"""控制台没有「默认工作区」：工作区总目录（`--workspaces-root`）下有 books/ 的子目录才可选（2026-09-30）。

旧法是 `GUJI_WORKSPACE` 指到某一本书、再扫它的兄弟目录——重启时带错一本，下拉框与册列表对不上。
"""
from __future__ import annotations

import argparse

import pytest


def _ws(root, name, books=("v1",), wid=None):
    d = root / name
    (d / "books").mkdir(parents=True)
    for b in books:
        (d / "books" / f"{b}.yaml").write_text("id: x\n", encoding="utf-8")
    if wid:
        (d / "workspace.yaml").write_text(f"id: {wid}\n", encoding="utf-8")
    return d


def test_discover_lists_children_of_root_not_siblings_of_env(tmp_path, monkeypatch):
    from open_guji_cv.console.routers.workspace import (
        allowed_workspaces, discover_workspaces, resolve_workspace_id)
    root = tmp_path / "gw"
    a = _ws(root, "96mid-四庫", ("vol01", "vol02"), wid="siku")
    b = _ws(root, "988g-北行", ("bxgb",), wid="bx")
    (root / "scripts").mkdir()                                    # 没有 books/ → 不列
    other = _ws(tmp_path, "elsewhere")                            # 总目录之外
    monkeypatch.setenv("GUJI_WORKSPACES_ROOT", str(root))
    monkeypatch.setenv("GUJI_WORKSPACE", str(other))              # 旧变量：不再决定列哪些
    got = {w["id"]: w for w in discover_workspaces()}
    assert set(got) == {"siku", "bx"} and got["siku"]["books"] == ["vol01", "vol02"]
    assert allowed_workspaces() == {str(a.resolve()), str(b.resolve())}
    assert resolve_workspace_id("bx") == str(b.resolve())
    assert resolve_workspace_id("elsewhere") is None              # 白名单之外认不出


def test_no_root_means_nothing_selectable(tmp_path, monkeypatch):
    from open_guji_cv.console.routers.workspace import allowed_workspaces, discover_workspaces
    monkeypatch.delenv("GUJI_WORKSPACES_ROOT", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(_ws(tmp_path, "w")))
    assert discover_workspaces() == [] and allowed_workspaces() == set()


def test_cmd_console_requires_root_and_drops_env_default(tmp_path, monkeypatch, capsys):
    from open_guji_cv import cli_v2
    from open_guji_cv.console import app as console_app_mod
    from open_guji_cv.console.auth import config as auth_config
    auth_config.set_config(no_auth=True)
    calls = {}
    monkeypatch.setattr(console_app_mod, "serve", lambda **kw: calls.update(kw))
    monkeypatch.delenv("GUJI_WORKSPACES_ROOT", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "some-book"))
    args = argparse.Namespace(port=8640, no_browser=True, host="127.0.0.1", no_auth=True,
                              root_path="", dev_idp=False, workspaces_root=None)
    with pytest.raises(SystemExit) as exc:
        cli_v2.cmd_console(args)
    assert exc.value.code != 0 and "--workspaces-root" in capsys.readouterr().err

    root = tmp_path / "gw"
    _ws(root, "w1", wid="one")
    args.workspaces_root = str(root)
    cli_v2.cmd_console(args)
    import os
    assert calls["port"] == 8640
    assert os.environ["GUJI_WORKSPACES_ROOT"] == str(root.resolve())
    assert "GUJI_WORKSPACE" not in os.environ                      # 继承来的默认被摘掉
    out = capsys.readouterr().out
    assert "one" in out and "已忽略环境变量 GUJI_WORKSPACE" in out
    monkeypatch.delenv("GUJI_WORKSPACES_ROOT", raising=False)
