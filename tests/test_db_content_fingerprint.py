"""库指纹是**内容**指纹，不是文件指纹（2026-09-20，用户定「中期建议」）。

此前 `db_fingerprint` 取 `(mtime_ns, size, exemplars 行数)`：备份复制、VACUUM、
边跑边审时消费者落一条人裁，全都让 bxgb 全书 Step5+ 过期——rerun10 跑到一半用户
confirm 落库（00:26:58Z），跑完 `status` 就多出一截过期，还得补一轮。现在只看匹配器
会读到的四张表的 (条数, 最大 rowid, 最新时间戳)；`seed_admit` 的人裁通道更窄，
只看 `provenance='human'` 的准入台账。
"""
from __future__ import annotations

import os
import shutil
import sqlite3

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from open_guji_cv.clustering import glyph_db as glyph_db_mod
from open_guji_cv.clustering.audit import evict_instance
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.steps.glyph_match import db_fingerprint, human_verdicts_fingerprint


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    img = (rng.integers(0, 2, (64, 64), dtype=np.uint8) * 255)
    return cv2.imencode(".png", img)[1].tobytes()


def _admit(db, iid, provenance, seed=1, char="字"):
    ok = db.admit_instance(iid, char, _png(seed), provenance=provenance,
                           edition_tag="bk", page="1", col=1, idx=seed)
    db.conn.commit()
    return ok


@pytest.fixture
def db(tmp_path):
    d = GlyphDB(tmp_path / "glyph.db")
    _admit(d, "v2:bk:1:1:1", "align", 1)
    _admit(d, "v2:bk:1:1:2", "human", 2)
    yield d
    d.close()


def test_touch_copy_and_vacuum_do_not_change_fingerprint(db, tmp_path):
    """与判决无关的文件操作：mtime 被 touch、复制到别处、VACUUM——指纹都不该动。"""
    path = db.path if hasattr(db, "path") else tmp_path / "glyph.db"
    fp0, h0 = db_fingerprint(path), human_verdicts_fingerprint(path)
    st = os.stat(path)
    os.utime(path, (st.st_atime + 1000, st.st_mtime + 1000))
    assert db_fingerprint(path) == fp0, "touch mtime 不该动指纹"
    db.conn.execute("VACUUM")
    assert db_fingerprint(path) == fp0, "VACUUM 不该动指纹"
    copy = tmp_path / "copy.db"
    shutil.copy(path, copy)
    assert db_fingerprint(copy) == fp0 and human_verdicts_fingerprint(copy) == h0, \
        "同内容的副本指纹必须相同（备份/迁移不该让产物过期）"


def test_align_admission_changes_db_fingerprint_but_not_human(db, tmp_path):
    path = tmp_path / "glyph.db"
    fp0, h0 = db_fingerprint(path), human_verdicts_fingerprint(path)
    assert _admit(db, "v2:bk:1:1:3", "align", 3)
    assert db_fingerprint(path) != fp0, "机器进库改变了匹配器的输入，glyph_match 该过期"
    assert human_verdicts_fingerprint(path) == h0, "机器进库与人裁通道无关，seed_admit 不该跟着白跑"


def test_human_admission_changes_both(db, tmp_path):
    path = tmp_path / "glyph.db"
    fp0, h0 = db_fingerprint(path), human_verdicts_fingerprint(path)
    assert _admit(db, "v2:bk:1:1:4", "human", 4)
    assert db_fingerprint(path) != fp0
    assert human_verdicts_fingerprint(path) != h0


def test_evict_and_readmit_within_one_second_is_visible(db, tmp_path):
    """人裁改判 = 撤旧再进：条数不变、时间戳可能同秒，靠 rowid 单调递增看见它。"""
    path = tmp_path / "glyph.db"
    _admit(db, "v2:bk:1:1:5", "human", 5)          # 让被撤的那条不是最后一行
    fp0, h0 = db_fingerprint(path), human_verdicts_fingerprint(path)
    evict_instance(db, "v2:bk:1:1:2")
    assert _admit(db, "v2:bk:1:1:2", "human", 2, char="另")
    assert db_fingerprint(path) != fp0
    assert human_verdicts_fingerprint(path) != h0


def test_human_stale_rename_changes_human_fingerprint(db, tmp_path):
    """撤裁的另一种写法：provenance 改成 human_stale_<日期>（不删账）。"""
    path = tmp_path / "glyph.db"
    h0 = human_verdicts_fingerprint(path)
    db.conn.execute("UPDATE admissions SET provenance='human_stale_20260920' "
                    "WHERE instance_id='v2:bk:1:1:2'")
    db.conn.commit()
    assert human_verdicts_fingerprint(path) != h0


def test_refresh_patch_changes_fingerprint(db, tmp_path, monkeypatch):
    """重切后刷新图块/派生：instances 不进指纹，靠 refresh_instance_patch 碰 exemplars.added_at。"""
    path = tmp_path / "glyph.db"
    fp0 = db_fingerprint(path)
    monkeypatch.setattr(glyph_db_mod, "_now", lambda: "2099-01-01T00:00:00+00:00")
    assert db.refresh_instance_patch("v2:bk:1:1:1", _png(11))
    assert db_fingerprint(path) != fp0, "只换了图块与派生、没碰 added_at，指纹就看不见"


def test_missing_and_unreadable_db_do_not_crash(tmp_path):
    assert db_fingerprint(tmp_path / "nope.db") == "nodb"
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a sqlite file at all")
    fp = db_fingerprint(junk)
    assert fp and fp != "nodb", "读不了的文件退回 stat 戳，不抛"
    assert human_verdicts_fingerprint(junk) == fp, "同一退路"


def test_seed_admit_params_use_human_only_fingerprint(db, tmp_path):
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    path = tmp_path / "glyph.db"
    p = SeedAdmitParams(db_path=str(path))
    assert p.human_fingerprint == human_verdicts_fingerprint(path)
    assert p.human_fingerprint != db_fingerprint(path)
