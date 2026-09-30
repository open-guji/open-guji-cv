# -*- coding: utf-8 -*-
"""近似字侧表（overview#276）的 store 导出、重建与云端↔服务器三方同步。

复用 `test_glyph_store_sync_merge.py` 的两克隆环境（remote 裸仓 + srv 服务器 + hmain 推 main）：
近似标记两个方向都要过得去、撤销要同步且不复活、db 静默丢了近似标记时删除护栏要拦下。
"""
from __future__ import annotations

import json
from pathlib import Path

from open_guji_cv.clustering.audit import evict_instance
from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store
from open_guji_cv.clustering.store_merge import unexplained_approx_deletions

from test_glyph_store_sync_merge import BOOK, _admit, _git, env  # noqa: F401  (env 是 fixture)

IID = "v2:v006:1:1:2"          # Env 初始的三例之一（「以」）


def _store_apx(store: Path) -> dict[str, dict]:
    f = store / "approx_labels.jsonl"
    return {json.loads(l)["instance_id"]: json.loads(l)
            for l in f.read_text(encoding="utf-8").splitlines() if l.strip()} if f.exists() else {}


def _remote_apx(env) -> dict[str, dict]:
    env.remote_ids()                                   # 顺带把 peek 克隆拉到最新
    return _store_apx(env.tmp / "peek" / BOOK / "output" / "glyph_store")


def _db_apx(p: Path) -> dict | None:
    g = GlyphDB(p)
    try:
        return g.approx_of(IID)
    finally:
        g.close()


def test_export_rebuild_roundtrip(tmp_path):
    p = tmp_path / "a.db"
    g = GlyphDB(p)
    iid = _admit(g, 2, "以")
    g.set_approx(iid, "以", ids="⿰𠄌人", note="n", reviewer="r", at="2026-09-29T01:00:00+00:00")
    g.clear_approx(iid, at="2026-09-29T02:00:00+00:00")
    g.set_approx(iid, "以", ids="⿰𠄌人", at="2026-09-29T03:00:00+00:00")
    counts = export_store(g, tmp_path / "st")
    g.close()
    assert counts["approx_labels"] == 1 and counts["approx_clears"] == 1
    rebuild_from_store(tmp_path / "st", tmp_path / "b.db")
    g = GlyphDB(tmp_path / "b.db")
    assert g.approx_of(iid) == {"instance_id": iid, "label": "以", "ids": "⿰𠄌人", "note": None,
                                "reviewer": None, "created_at": "2026-09-29T03:00:00+00:00"}
    assert g.conn.execute("SELECT count(*) FROM approx_clears").fetchone()[0] == 1
    g.close()


def test_empty_side_table_exports_empty_files(tmp_path):
    """没有近似例的库：多出两个空文件，其余导出不变（store 里原有文件一个字节都不动）。"""
    p = tmp_path / "a.db"
    g = GlyphDB(p)
    _admit(g, 1, "之")
    export_store(g, tmp_path / "st")
    g.close()
    assert (tmp_path / "st" / "approx_labels.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "st" / "approx_clears.jsonl").read_text(encoding="utf-8") == ""


def test_main_marks_approx_reaches_server(env):
    """H 在 main 上给一例标近似：服务器同步后 db 里有，下一轮也不会被服务器旧状态冲掉。"""
    assert env.sync() == 0
    env.h_change(lambda g: g.set_approx(IID, "以", ids="⿰𠄌人"), msg="H：标近似")
    assert env.sync() == 0
    assert _db_apx(env.db)["ids"] == "⿰𠄌人", "上游标的近似要套进服务器 db（闸要用）"
    assert IID in _remote_apx(env)
    assert env.sync() == 0
    assert IID in _remote_apx(env)


def test_main_marks_approx_first_run_without_base(env):
    """服务器第一次跑（没记过 base）：同样不能把 main 上的近似标记冲掉。"""
    env.h_change(lambda g: g.set_approx(IID, "以"), msg="H：标近似")
    assert env.sync() == 0
    assert IID in _remote_apx(env) and _db_apx(env.db) is not None


def test_server_marks_approx_reaches_main(env):
    assert env.sync() == 0
    g = GlyphDB(env.db)
    g.set_approx(IID, "以", note="服务器上人裁勾的")
    g.close()
    assert env.sync() == 0, "只标了近似、别的没动，也要导出推上去"
    assert _remote_apx(env)[IID]["note"] == "服务器上人裁勾的"
    # H 从 main 重建本机库，近似标记在
    _git(env.hmain, "pull", "-q")
    rebuild_from_store(env.hmain / BOOK / "output" / "glyph_store", env.tmp / "h2.db")
    g = GlyphDB(env.tmp / "h2.db")
    assert g.approx_of(IID)["note"] == "服务器上人裁勾的"
    g.close()


def test_upstream_clear_not_resurrected(env):
    g = GlyphDB(env.db)
    g.set_approx(IID, "以", at="2026-09-29T01:00:00+00:00")
    g.close()
    assert env.sync() == 0
    env.h_change(lambda g: g.clear_approx(IID), msg="H：撤近似")
    assert env.sync() == 0
    assert _db_apx(env.db) is None, "main 上撤了，服务器 db 跟着撤"
    assert IID not in _remote_apx(env)
    assert env.sync() == 0
    assert IID not in _remote_apx(env), "下一轮不能被写回去"


def test_server_clear_syncs(env):
    g = GlyphDB(env.db)
    g.set_approx(IID, "以", at="2026-09-29T01:00:00+00:00")
    g.close()
    assert env.sync() == 0
    g = GlyphDB(env.db)
    g.clear_approx(IID)
    g.close()
    assert env.sync() == 0, "有撤销审计的撤近似，护栏放行"
    assert IID not in _remote_apx(env)
    assert IID in (env.store / "approx_clears.jsonl").read_text(encoding="utf-8")


def test_both_sides_changed_newer_wins(env):
    env.h_change(lambda g: g.set_approx(IID, "以", note="H", at="2026-09-29T01:00:00+00:00"),
                 msg="H：标近似")
    g = GlyphDB(env.db)
    g.set_approx(IID, "以", note="服务器", at="2026-09-29T05:00:00+00:00")   # 服务器更晚
    g.close()
    assert env.sync() == 0
    assert _remote_apx(env)[IID]["note"] == "服务器"


def test_guard_blocks_silent_approx_loss(env):
    """db 里近似标记静默没了（没有撤销审计）：拒绝导出，store 与远端都留着。"""
    g = GlyphDB(env.db)
    g.set_approx(IID, "以")
    g.close()
    assert env.sync() == 0
    g = GlyphDB(env.db)
    g.conn.execute("DELETE FROM approx_labels")
    g.conn.commit()
    g.close()
    assert env.sync() == 1
    assert IID in _store_apx(env.store) and IID in _remote_apx(env)


def test_guard_unit_evicted_instance_is_instance_guards_job(tmp_path):
    """实例整个撤了（有 evictions 审计）：近似行跟着走，近似护栏不重复拦。"""
    p = tmp_path / "a.db"
    g = GlyphDB(p)
    iid = _admit(g, 2, "以", "2026-09-27T20:00:00+00:00")
    g.set_approx(iid, "以", at="2026-09-27T20:00:00+00:00")
    export_store(g, tmp_path / "st")
    evict_instance(g, iid, reason="t")
    rep = unexplained_approx_deletions(g.conn, tmp_path / "st")
    g.close()
    assert rep == {"planned": 0, "explained": 0, "unexplained": []}
