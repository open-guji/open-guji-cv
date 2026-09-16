# -*- coding: utf-8 -*-
"""工作区是**每请求一个**：两个标签页能同时在两个工作区上干活。

用户 2026-09-15 定的形态：这个值只存在于浏览器，每个请求用
`X-Guji-Workspace` 头带过来。服务端不持有「当前工作区」——否则两个标签页
会互相打架（A 切一下，B 的下一次请求就跟着变）。

这里不起 HTTP 服务，直接验底层契约：contextvar 覆盖生效、按请求隔离、
并发不串、各个根都跟着走。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from open_guji_cv.core.workspace import (
    products_root, reset_workspace_override, set_workspace_override, workspace_root,
)


def test_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "from_env"))
    assert workspace_root() == (tmp_path / "from_env").resolve()

    tok = set_workspace_override(str(tmp_path / "from_request"))
    try:
        assert workspace_root() == (tmp_path / "from_request").resolve()
        # 各个根都得跟着走，不只是 workspace_root 自己
        assert products_root() == (tmp_path / "from_request").resolve() / "products"
    finally:
        reset_workspace_override(tok)
    assert workspace_root() == (tmp_path / "from_env").resolve()


def test_empty_override_means_repo_default(tmp_path, monkeypatch):
    """空串 = 明确「不用工作区，跑仓内样本」，与 None（没覆盖）区分开。"""
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "from_env"))
    tok = set_workspace_override("")
    try:
        assert workspace_root() is None
    finally:
        reset_workspace_override(tok)


def test_concurrent_requests_do_not_leak(tmp_path):
    """并发下互不串——contextvar 按执行上下文隔离，这是「两个标签页」的地基。"""
    def one(name: str) -> str:
        tok = set_workspace_override(str(tmp_path / name))
        try:
            # 多读几次，给串味留出机会
            seen = {str(workspace_root()) for _ in range(20)}
            assert len(seen) == 1, f"同一上下文内自己都变了：{seen}"
            return seen.pop()
        finally:
            reset_workspace_override(tok)

    names = [f"ws{i % 4}" for i in range(32)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(one, names))

    for name, g in zip(names, got):
        assert g == str((tmp_path / name).resolve()), f"{name} 拿到了 {g}"
