"""匹配器特征缓存（`seeding._matcher_arrays`，GUJI-647）：命中、部分命中、关掉缓存三种情况下，
匹配器里的特征矩阵、归一图与逐条现算的逐位相同；库变了换一代，不读到拼凑的。"""

from pathlib import Path

import numpy as np

from open_guji_cv.clustering import seeding
from open_guji_cv.clustering.font_glyphs import FontSpec, import_font
from open_guji_cv.clustering.glyph_db import GlyphDB


def _spec() -> FontSpec:
    from open_guji_cv.clustering.font_candidates import _font_files
    return FontSpec(edition_tag="font:t", font_paths=[Path(f) for f in _font_files()[:1]])


def _db(path: Path, chars) -> GlyphDB:
    db = GlyphDB(path)
    import_font(db, _spec(), chars)
    return db


def _snapshot(m):
    return ([str(x) for x in m._ids], [str(x) for x in m._chars], np.asarray(m._F).copy(),
            np.stack(m._patches).copy())


def _same(a, b):
    assert a[0] == b[0] and a[1] == b[1]
    assert a[2].dtype == b[2].dtype == np.float32 and np.array_equal(a[2], b[2])
    assert a[3].dtype == b[3].dtype and np.array_equal(a[3], b[3])


def test_cache_hit_and_partial_hit_equal_fresh_extraction(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    db = _db(tmp_path / "g.db", ["一", "二", "口", "日"])
    monkeypatch.setenv("GUJI_MATCHER_FEAT_CACHE", "0")
    fresh = _snapshot(seeding.load_matcher_from_db(db)[0])
    monkeypatch.delenv("GUJI_MATCHER_FEAT_CACHE")
    miss = _snapshot(seeding.load_matcher_from_db(db)[0])            # 没缓存：现算并写一代
    _same(fresh, miss)
    gens = [p for p in (tmp_path / "cache" / "glyph_feats").rglob("current")]
    assert len(gens) == 1
    calls = []
    real = seeding._unpng
    monkeypatch.setattr(seeding, "_unpng", lambda d: calls.append(1) or real(d))
    hit = _snapshot(seeding.load_matcher_from_db(db)[0])             # 全命中：一张都不解
    _same(fresh, hit)
    assert calls == []
    # 库变了：多两个字。命中的照抄，缺的两条现算，换成新的一代
    import_font(db, _spec(), ["一", "二", "口", "日", "永", "山"])
    part = _snapshot(seeding.load_matcher_from_db(db)[0])
    assert len(calls) == 2
    monkeypatch.setenv("GUJI_MATCHER_FEAT_CACHE", "0")
    _same(_snapshot(seeding.load_matcher_from_db(db)[0]), part)
    gen_dirs = [p for p in gens[0].parent.iterdir() if p.is_dir()]
    assert len(gen_dirs) == 1 and gens[0].read_text() == gen_dirs[0].name


def test_matcher_matrix_is_reused_not_restacked(tmp_path, monkeypatch):
    """装库时把整张矩阵交给匹配器：匹配不再把 `_feats` 堆一遍（同一个对象），结果与关掉缓存时相同。"""
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    db = _db(tmp_path / "g.db", ["一", "二", "口", "日"])
    m, _ = seeding.load_matcher_from_db(db)
    F = m._F
    q = m._patches[2].copy()
    r = m.match(q)
    assert m._F is F
    monkeypatch.setenv("GUJI_MATCHER_FEAT_CACHE", "0")
    m2, _ = seeding.load_matcher_from_db(db)
    assert m2.match(q).to_dict() == r.to_dict()


def test_batch_knn_is_on_by_default_and_off_keeps_old_params_hash():
    """v0.5.5 起缺省开（用户 10-21 定）；显式关掉时不进参数 dump，参数哈希与以前的缺省相同。"""
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    base = dict(db_path="x.db", db_fingerprint="f", borrow_fingerprint="", font_tier=False)
    on = GlyphMatchParams(**base)
    assert on.batch_knn is True and on.model_dump(mode="json")["batch_knn"] is True
    off = GlyphMatchParams(**base, batch_knn=False)
    assert "batch_knn" not in off.model_dump(mode="json")
    assert params_hash(on) != params_hash(off)


def test_page_batch_feeds_precomputed_sims_and_matches_like_cell_by_cell(tmp_path, monkeypatch):
    from open_guji_cv.steps.glyph_match import _PageBatch
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    db = _db(tmp_path / "g.db", ["一", "二", "口", "日", "永", "山"])
    m, _ = seeding.load_matcher_from_db(db)
    queries = [m._patches[i].copy() for i in (0, 2, 4, 2)]          # 同一张图出现两次
    batch = _PageBatch(m, queries)
    batch.CHUNK = 3
    seen = []
    real = m.match
    monkeypatch.setattr(m, "match", lambda norm, **kw: seen.append(kw.get("sims") is not None) or real(norm, **kw))
    for q in queries:
        assert batch.match(q, exclude_id=None).to_dict() == real(q).to_dict()
    assert seen == [True] * 4
    other = np.zeros_like(queries[0])                                 # 不在本页查询里：照旧逐格算
    seen.clear()
    batch.match(other)
    assert seen == [False]
