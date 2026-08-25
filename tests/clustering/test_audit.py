"""audit.py 单测：形离群/竞争字判定、OCR 并旗、撤库删净。"""

import random

import numpy as np
import pytest

from open_guji_cv.clustering.audit import (AuditEntry, AuditFinding,
                                           apply_ocr, evict_instance,
                                           shape_audit)
from open_guji_cv.clustering.synth import synthetic_glyph


def _norm(ch: str, jitter: int = 0) -> np.ndarray:
    g = synthetic_glyph(random.Random(ord(ch))).astype(np.uint8)
    if jitter:
        g = np.roll(g, jitter, axis=1)
    return g


def _entries():
    es = []
    for i in range(3):                       # 「天」三例，微小平移仍同形
        es.append(AuditEntry(f"b:1:1:{i}", "天", "天", _norm("天", i)))
    for i in range(3):
        es.append(AuditEntry(f"b:2:1:{i}", "地", "地", _norm("地", i)))
    # 标成「天」但形是「地」——错标实例
    es.append(AuditEntry("b:3:1:0", "天", "天", _norm("地", 1)))
    return es


def test_shape_audit_flags_mislabeled():
    f = shape_audit(_entries())
    bad = f["b:3:1:0"]
    assert "rival" in bad.flags          # 形上更像「地」
    assert bad.other_char == "地"
    assert "outlier" in bad.flags        # 与同字「天」对不上
    # 正牌「天」例互相覆盖良好，不被打旗
    assert f["b:1:1:0"].flags == []
    assert f["b:1:1:0"].best_same >= 0.9
    # 同字参照一定被量到（即使全局近邻被别的字占掉）
    assert f["b:1:1:1"].same_peer is not None


def test_shape_audit_singleton_no_shape_flags():
    es = _entries() + [AuditEntry("b:9:1:0", "孤", "孤", _norm("孤"))]
    f = shape_audit(es)
    assert f["b:9:1:0"].best_same < 0    # 无同字参照的标记值
    assert "outlier" not in f["b:9:1:0"].flags


def test_apply_ocr_flags_high_conf_mismatch():
    f = {"a": AuditFinding("a", "天"), "b": AuditFinding("b", "天"),
         "c": AuditFinding("c", "天")}
    apply_ocr(f, {"a": ("地", 0.95), "b": ("天", 0.99), "c": ("地", 0.3)},
              semantic_fn=lambda c: c)
    assert f["a"].flags == ["ocr"]
    assert f["b"].flags == []            # 同字不打旗
    assert f["c"].flags == []            # 低置信异议不采


def test_evict_instance_removes_everything(tmp_path):
    import cv2
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db = GlyphDB(tmp_path / "g.db")
    try:
        n = _norm("天")
        png = cv2.imencode(".png", (255 - n * 255).astype(np.uint8))[1].tobytes()
        assert db.admit_instance("b:1:1:0", "天", png, provenance="human")
        assert evict_instance(db, "b:1:1:0") == "天"
        for t in ("admissions", "exemplars", "derived", "instances"):
            assert db.conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE instance_id='b:1:1:0'"
            ).fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM glyphs").fetchone()[0] == 0
        assert evict_instance(db, "b:1:1:0") is None     # 幂等
    finally:
        db.close()


def test_evict_drops_empty_glyph_and_decrements(tmp_path):
    """撤最后一个刻例要连字头一起删；还有别的刻例则只把 n_confirmed 减下来。

    回归：原实现的清壳 SQL 引用了 `instances.glyph_id`——那列不存在，SQLite
    把它当相关子查询解析成外层的 `glyphs.glyph_id`，`NOT IN` 恒为假，DELETE
    永不生效。上面那条老用例查不出来：它撤完之后两张表都空了，空子查询的
    `NOT IN` 恰好为真，删除照样发生。**只有库里还剩别的刻例时才露馅**——
    生产库因此攒了 34 个零刻例的空壳字头。
    """
    import cv2
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db = GlyphDB(tmp_path / "g.db")
    try:
        for iid, ch in (("b:1:1:0", "天"), ("b:1:1:1", "天"), ("b:1:1:2", "地")):
            n = _norm(ch)
            png = cv2.imencode(".png", (255 - n * 255).astype(np.uint8))[1].tobytes()
            assert db.admit_instance(iid, ch, png, provenance="human")

        assert evict_instance(db, "b:1:1:0") == "天"
        assert db.conn.execute(
            "SELECT n_confirmed FROM glyphs WHERE char='天'").fetchone()[0] == 1

        assert evict_instance(db, "b:1:1:2") == "地"
        assert db.conn.execute(
            "SELECT COUNT(*) FROM glyphs WHERE char='地'").fetchone()[0] == 0
        assert db.conn.execute(
            """SELECT COUNT(*) FROM glyphs g WHERE NOT EXISTS
                 (SELECT 1 FROM exemplars e WHERE e.glyph_id=g.glyph_id)"""
        ).fetchone()[0] == 0
    finally:
        db.close()
