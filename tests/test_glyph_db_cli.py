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

import open_guji_cv.cli_glyph_db as main_mod
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
    from open_guji_cv.feedback import replay as replay_mod
    monkeypatch.setattr(replay_mod, "replay_after_rebuild", lambda *a, **k: {"stub": True})
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


# ── 借库（冷启动，2026-09-27 全唐文）：--extra-store / workspace.yaml glyph_lib.borrow / --no-borrow ──

@pytest.fixture()
def capture_extras(monkeypatch, tmp_path):
    seen = {}

    def _fake_rebuild(store_dir, db_path, extra_stores=()):
        seen["extras"] = [Path(x) for x in extra_stores]
        return {"instances": 0}

    monkeypatch.setattr(glyph_db_mod, "rebuild_from_store", _fake_rebuild)
    monkeypatch.setattr(glyph_db_mod, "assert_db_not_silently_empty", lambda *a, **k: None)
    from open_guji_cv.feedback import replay as replay_mod
    monkeypatch.setattr(replay_mod, "replay_after_rebuild", lambda *a, **k: {"stub": True})
    monkeypatch.setenv("GUJI_GLYPH_DB", str(tmp_path / "glyph.db"))
    return seen


def _ws_with_borrow(monkeypatch, tmp_path, borrow):
    ws = tmp_path / "qtw"
    ws.mkdir()
    import yaml
    (ws / "workspace.yaml").write_text(
        yaml.safe_dump({"id": "qtw", "glyph_lib": {"borrow": borrow}}, allow_unicode=True),
        encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    return ws


def test_borrow_from_workspace_yaml(monkeypatch, tmp_path, capture_extras):
    ws = _ws_with_borrow(monkeypatch, tmp_path, ["../siku/output/glyph_store"])
    main_mod.cmd_glyph_db(Namespace(action="rebuild", path=None, store=None))
    assert capture_extras["extras"] == [ws / "../siku/output/glyph_store"]


def test_no_borrow_overrides_workspace_yaml(monkeypatch, tmp_path, capture_extras):
    _ws_with_borrow(monkeypatch, tmp_path, ["../siku/output/glyph_store"])
    main_mod.cmd_glyph_db(Namespace(action="rebuild", path=None, store=None, no_borrow=True))
    assert capture_extras["extras"] == []


def test_extra_store_cli_wins_and_ignores_glyph_store_env(monkeypatch, tmp_path, capture_extras):
    ws = _ws_with_borrow(monkeypatch, tmp_path, ["../siku/output/glyph_store"])
    monkeypatch.setenv("GUJI_GLYPH_STORE", str(tmp_path / "own_store"))
    main_mod.cmd_glyph_db(Namespace(action="rebuild", path=None, store=None,
                                    extra_store=["/abs/other/glyph_store", "rel/store"]))
    assert capture_extras["extras"] == [Path("/abs/other/glyph_store"), ws / "rel/store"]


def test_empty_borrow_means_own_library_only(monkeypatch, tmp_path, capture_extras):
    _ws_with_borrow(monkeypatch, tmp_path, [])
    main_mod.cmd_glyph_db(Namespace(action="rebuild", path=None, store=None))
    assert capture_extras["extras"] == []
