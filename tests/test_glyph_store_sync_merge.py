# -*- coding: utf-8 -*-
"""`scripts/glyph_store_sync.py` 的合并逻辑（overview#234）：两个 git 克隆模拟服务器与 main。

09-28 事故：H 往 main 进了 14 例「聞」，服务器 pull 下来但 db 不知道，下一轮导出把它们从 store
删掉推了上去。这里复现它，并测撤例双向同步、两边同时改、删除护栏、推送失败后的下一轮。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.audit import evict_instance
from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store

BOOK = "qtw"


def _load():
    spec = importlib.util.spec_from_file_location(
        "glyph_store_sync", Path(__file__).resolve().parent.parent / "scripts" / "glyph_store_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _png(k: int) -> bytes:
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (6 + k % 20, 10), (70, 70 - k % 15), 0, 4)
    cv2.line(img, (10, 10 + k % 30), (70, 40), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _admit(db: GlyphDB, slot: int, ch: str, ts: str | None = None) -> str:
    iid = f"v2:v006:1:1:{slot}"
    assert db.admit_instance(iid, ch, _png(slot), provenance="human", page="1", col=1, idx=slot)
    if ts:
        db.conn.execute("UPDATE admissions SET admitted_at=? WHERE instance_id=?", (ts, iid))
        db.conn.execute("UPDATE instances SET updated_at=? WHERE instance_id=?", (ts, iid))
        db.conn.execute("UPDATE exemplars SET added_at=? WHERE instance_id=?", (ts, iid))
    db.conn.commit()
    return iid


def _store_ids(store: Path) -> set[str]:
    f = store / "exemplars.jsonl"
    return {json.loads(l)["instance_id"] for l in f.read_text(encoding="utf-8").splitlines()
            if l.strip()} if f.exists() else set()


def _db_ids(db_path: Path) -> set[str]:
    db = GlyphDB(db_path)
    try:
        return {r[0] for r in db.conn.execute("SELECT instance_id FROM exemplars")}
    finally:
        db.close()


class Env:
    """remote（裸仓）＋ srv（服务器：有 glyph.db、跑同步）＋ hmain（H：推 main）。"""

    def __init__(self, tmp: Path, m):
        self.tmp, self.m = tmp, m
        self.remote = tmp / "remote.git"
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.srv = tmp / "srv"
        _git(tmp, "clone", "-q", str(self.remote), str(self.srv))
        self.ws = self.srv / BOOK
        self.db = self.ws / "output" / "glyph.db"
        self.store = self.ws / "output" / "glyph_store"
        (self.ws / "output").mkdir(parents=True)
        g = GlyphDB(self.db)
        g.set_book_edition("quantangwen")
        for k, ch in enumerate("之以令", 1):
            _admit(g, k, ch, "2026-09-27T20:00:00+00:00")
        export_store(g, self.store)
        g.close()
        (self.srv / ".gitignore").write_text("*.db\n", encoding="utf-8")
        _git(self.srv, "add", ".")
        _git(self.srv, "commit", "-q", "-m", "定时同步：字形库 store：初始")
        _git(self.srv, "push", "-q", "-u", "origin", "main")
        self.hmain = tmp / "hmain"
        _git(tmp, "clone", "-q", str(self.remote), str(self.hmain))

    def sync(self) -> int:
        return self.m.main(["--root", str(self.srv)])

    def h_change(self, fn, msg="H：进「聞」") -> None:
        """H 在 main 上：从 store 重建本机库 → 改库 → 导出 → 推。"""
        _git(self.hmain, "pull", "-q")
        st = self.hmain / BOOK / "output" / "glyph_store"
        hdb = self.tmp / "h.db"
        rebuild_from_store(st, hdb)
        g = GlyphDB(hdb)
        fn(g)
        export_store(g, st)
        g.close()
        _git(self.hmain, "add", "-A")
        _git(self.hmain, "commit", "-q", "-m", msg)
        _git(self.hmain, "push", "-q")

    def remote_ids(self) -> set[str]:
        out = self.tmp / "peek"
        if out.exists():
            _git(out, "pull", "-q")
        else:
            _git(self.tmp, "clone", "-q", str(self.remote), str(out))
        return _store_ids(out / BOOK / "output" / "glyph_store")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_FEEDBACK_DIR", "GUJI_PRODUCTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    m = _load()
    monkeypatch.setattr(m, "STATE_DIR", tmp_path / "state")
    return Env(tmp_path, m)


H14 = [f"v2:v006:1:2:{i}" for i in range(1, 15)]


def _h_add_14(g: GlyphDB) -> None:
    for i in range(1, 15):
        assert g.admit_instance(f"v2:v006:1:2:{i}", "聞", _png(40 + i), provenance="human",
                                page="1", col=2, idx=i)
    g.conn.commit()


def test_incident_main_ahead_server_db_stale_no_state(env):
    """原样复现 09-28：服务器上从没记过 base（第一次跑新逻辑），main 多了 14 例，服务器 db 是旧的。"""
    env.h_change(_h_add_14)
    assert env.sync() == 0
    assert set(H14) <= _store_ids(env.store), "14 例被服务器旧库冲掉了"
    assert set(H14) <= env.remote_ids()
    assert set(H14) <= _db_ids(env.db), "上游进的刻例要套进服务器 db（匹配要用）"
    # 下一轮：无变化，也不会删
    assert env.sync() == 0
    assert set(H14) <= env.remote_ids()


def test_incident_with_state_after_previous_round(env):
    assert env.sync() == 0                       # 上线后正常跑过一轮，记下了 base
    env.h_change(_h_add_14)
    assert env.sync() == 0
    assert set(H14) <= env.remote_ids()
    assert set(H14) <= _db_ids(env.db)


def test_server_eviction_syncs(env):
    g = GlyphDB(env.db)
    evict_instance(g, "v2:v006:1:1:2", reason="体检撤库")
    g.close()
    assert env.sync() == 0
    ids = env.remote_ids()
    assert "v2:v006:1:1:2" not in ids and "v2:v006:1:1:1" in ids
    ev = (env.store / "evictions.jsonl").read_text(encoding="utf-8")
    assert "v2:v006:1:1:2" in ev, "撤例审计要随 store 导出"


def test_upstream_eviction_not_resurrected(env):
    """H #201 那种：main 上撤了，服务器 db 里还有——不能被写回去。"""
    env.h_change(lambda g: evict_instance(g, "v2:v006:1:1:3", reason="H #201"), msg="H：撤")
    assert env.sync() == 0
    assert "v2:v006:1:1:3" not in env.remote_ids()
    assert "v2:v006:1:1:3" not in _db_ids(env.db)
    assert env.sync() == 0
    assert "v2:v006:1:1:3" not in env.remote_ids()


def test_both_sides_changed(env):
    """服务器刚审进一例（还没导出），main 上 H 又进了 14 例、撤了一例：都要留下。"""
    g = GlyphDB(env.db)
    srv_new = _admit(g, 9, "天")
    g.close()

    def h(g):
        _h_add_14(g)
        evict_instance(g, "v2:v006:1:1:1", reason="H 撤")
    env.h_change(h)
    assert env.sync() == 0
    ids = env.remote_ids()
    assert srv_new in ids
    assert set(H14) <= ids
    assert "v2:v006:1:1:1" not in ids


def test_same_instance_relabeled_both_sides_newer_wins(env):
    iid = "v2:v006:1:1:2"

    def h(g):
        evict_instance(g, iid)
        _admit(g, 2, "巳", "2026-09-28T10:00:00+00:00")
    env.h_change(h, msg="H：改判")
    g = GlyphDB(env.db)
    evict_instance(g, iid)
    _admit(g, 2, "已", "2026-09-28T11:00:00+00:00")      # 服务器改判更晚
    g.close()
    assert env.sync() == 0
    row = [json.loads(l) for l in (env.store / "exemplars.jsonl").read_text(encoding="utf-8").splitlines()
           if json.loads(l)["instance_id"] == iid]
    assert [r["char"] for r in row] == ["已"]


def test_guard_blocks_unexplained_deletion(env):
    """db 里静默少了一例（没有撤例审计）：拒绝导出，store 与远端都不动。"""
    assert env.sync() == 0
    g = GlyphDB(env.db)
    for t in ("admissions", "exemplars", "derived", "instances"):
        g.conn.execute(f"DELETE FROM {t} WHERE instance_id='v2:v006:1:1:1'")
    _admit(g, 8, "地")                                   # 同时还有正常的新增
    g.conn.commit()
    g.close()
    assert env.sync() == 1
    assert "v2:v006:1:1:1" in _store_ids(env.store)
    assert "v2:v006:1:1:1" in env.remote_ids()


def test_guard_blocks_when_merge_base_unknown(env, monkeypatch):
    """合并失效（找不到 base）时，护栏兜底：旧库导出不许删掉 main 上多出来的刻例。"""
    monkeypatch.setattr(env.m, "merge_base", lambda root, ws: None)
    env.h_change(_h_add_14)
    assert env.sync() == 1
    assert set(H14) <= env.remote_ids()


def test_push_rejected_then_next_round(env, monkeypatch):
    """推送被拒（上游这期间又有人推）：本轮不记 base，下一轮合并后照样推上去，谁都不丢。"""
    assert env.sync() == 0
    g = GlyphDB(env.db)
    srv_new = _admit(g, 9, "天")
    g.close()
    real_git = env.m.git

    def racing_git(root, *args, check=True):
        if args[:1] == ("push",) and not getattr(racing_git, "done", False):
            racing_git.done = True
            env.h_change(_h_add_14)                     # 在我们推之前 H 抢先推了
        return real_git(root, *args, check=check)
    monkeypatch.setattr(env.m, "git", racing_git)
    assert env.sync() == 1
    assert env.sync() == 0
    ids = env.remote_ids()
    assert srv_new in ids and set(H14) <= ids
    assert set(H14) <= _db_ids(env.db)


def test_merge_is_idempotent_and_keeps_font_domain(env):
    """增量合并不整库重建：db 里不导出的东西（字体域、未定字实例）原样留着。"""
    g = GlyphDB(env.db)
    g.conn.execute("INSERT INTO sources (source_id, edition_tag, kind, created_at) "
                   "VALUES ('font:x', 'font:x', 'font', '2026-01-01')")
    g.conn.commit()
    g.close()
    env.h_change(_h_add_14)
    assert env.sync() == 0
    g = GlyphDB(env.db)
    assert g.conn.execute("SELECT 1 FROM sources WHERE source_id='font:x'").fetchone()
    g.close()
    assert env.sync() == 0


def test_incident_exact_sequence_server_pulled_before_export(env):
    """事故原样的时序：服务器正常跑过一轮 → H 推 14 例 → 服务器 pull 到了（db 没跟）→
    服务器又审进一例、db 签名变了 → 导出。旧逻辑在这里把远端 14 例删光（实测 0/14）。"""
    assert env.sync() == 0
    env.h_change(_h_add_14)
    _git(env.srv, "pull", "-q")
    g = GlyphDB(env.db)
    srv_new = _admit(g, 9, "天")
    g.close()
    assert env.sync() == 0
    ids = env.remote_ids()
    assert set(H14) <= ids and srv_new in ids
