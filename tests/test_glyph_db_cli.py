"""`glyph-db` 子命令的 `--store` 路径解析（库路径 P0 另一半）。

`cmd_glyph_db` 曾经把 `args.store` 当裸 CWD 相对路径直传给
`rebuild_from_store` / `export_store`，不走 `core.workspace.glyph_store_path()`
——即使 `GUJI_WORKSPACE` 设对了也读不到工作区里的真源，静默读到仓内（或
CWD 下）另一个同名目录，exit 0、数字却全线变小。这里只验路径解析，不跑
真正的 rebuild（重的是 I/O，不是这段逻辑）。
"""

from argparse import Namespace
from pathlib import Path

import pytest

import open_guji_cv.__main__ as main_mod
from open_guji_cv.clustering import glyph_db as glyph_db_mod
from open_guji_cv.core import workspace as workspace_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("GUJI_WORKSPACE", "GUJI_GLYPH_STORE", "GUJI_GLYPH_DB"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def capture_store(monkeypatch, tmp_path):
    """打桩 rebuild_from_store，只抓它实际收到的 store 路径，不真跑。"""
    seen = {}

    def _fake_rebuild(store_dir, db_path):
        seen["store_dir"] = Path(store_dir)
        return {"instances": 0}

    def _fake_assert(db_path, store_dir=None):
        seen["assert_store_dir"] = Path(store_dir) if store_dir is not None else None

    monkeypatch.setattr(glyph_db_mod, "rebuild_from_store", _fake_rebuild)
    monkeypatch.setattr(glyph_db_mod, "assert_db_not_silently_empty", _fake_assert)
    monkeypatch.setenv("GUJI_GLYPH_DB", str(tmp_path / "glyph.db"))
    return seen


def _run(store):
    args = Namespace(action="rebuild", path=None, store=store)
    main_mod.cmd_glyph_db(args)


def test_no_store_uses_workspace_output_glyph_store(monkeypatch, tmp_path, capture_store):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))

    _run(None)

    assert capture_store["store_dir"] == ws / "output" / "glyph_store"


def test_no_store_no_workspace_uses_repo_sample_store(capture_store):
    _run(None)

    assert capture_store["store_dir"] == workspace_mod.REPO_ROOT / "output" / "glyph_store"


def test_relative_store_resolved_against_workspace_not_cwd(monkeypatch, tmp_path, capture_store):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.chdir(tmp_path)  # CWD 与工作区不同目录，确认真按工作区解释

    _run("glyph_store")

    assert capture_store["store_dir"] == ws / "glyph_store"


def test_absolute_store_overrides_workspace(monkeypatch, tmp_path, capture_store):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    abs_store = tmp_path / "elsewhere" / "glyph_store"

    _run(str(abs_store))

    assert capture_store["store_dir"] == abs_store
