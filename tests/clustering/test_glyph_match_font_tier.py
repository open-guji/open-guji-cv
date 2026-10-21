"""分级查库（`glyph_match.font_tier`，GUJI-726）：关着不进参数 dump；开了先查刻本库，命中弱才查整库，
查整库时结果与关着时相同。"""

from pathlib import Path

import pytest

from open_guji_cv.clustering import seeding
from open_guji_cv.clustering.font_glyphs import FontSpec, import_font
from open_guji_cv.clustering.glyph_db import GlyphDB


def _spec(tag: str) -> FontSpec:
    from open_guji_cv.clustering.font_candidates import _font_files
    return FontSpec(edition_tag=tag, font_paths=[Path(f) for f in _font_files()[:1]])


def _matcher(tmp_path, monkeypatch):
    """「刻本」三个字（用字体渲染冒充，id 不以 font: 起头）＋字体域六个字。"""
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    db = GlyphDB(tmp_path / "g.db")
    import_font(db, _spec("kb"), ["一", "二", "口"])
    import_font(db, _spec("font:t"), ["一", "二", "口", "日", "永", "山"])
    m, _ = seeding.load_matcher_from_db(db)
    return m


def test_font_tier_is_on_by_default_and_off_keeps_old_params_hash():
    """v0.5.5 起缺省开（用户 10-21 定）；显式关掉时不进参数 dump，参数哈希与以前的缺省相同。"""
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    base = dict(db_path="x.db", db_fingerprint="f", borrow_fingerprint="", batch_knn=False)
    dflt = GlyphMatchParams(**base)
    d = dflt.model_dump(mode="json")["font_tier"]
    assert len(d["family_fp"]) == 12                                  # 字组／形近字表的指纹自动填进来
    off = GlyphMatchParams(**base, font_tier=False)
    assert "font_tier" not in off.model_dump(mode="json")
    assert "font_tier" not in GlyphMatchParams(**base, font_tier=None).model_dump(mode="json")
    on = GlyphMatchParams(**base, font_tier={"cov": 0.99})
    assert on.model_dump(mode="json")["font_tier"]["cov"] == 0.99
    assert len({params_hash(dflt), params_hash(off), params_hash(on)}) == 3


def test_rule_defaults_and_unknown_keys():
    from open_guji_cv.steps.glyph_match import _FontTier
    assert _FontTier.rule(None) is None and _FontTier.rule(False) is None
    assert _FontTier.rule(True) == {"cov": 0.98, "margin": 0.03, "min_n": 0,       # GUJI-726 的 T98
                                    "family": True, "family_fp": None}
    assert _FontTier.rule({"cov": 0.99})["cov"] == 0.99
    with pytest.raises(ValueError):
        _FontTier.rule({"covv": 0.99})


def test_keben_subset_keeps_only_non_font_rows(tmp_path, monkeypatch):
    from open_guji_cv.steps.glyph_match import _keben_subset
    m = _matcher(tmp_path, monkeypatch)
    sub = _keben_subset(m)
    assert len(m) == 9 and len(sub) == 3
    assert all(not i.startswith("font:") for i in sub._ids)
    assert sub.library_matrix().shape == (3, m.library_matrix().shape[1])
    assert sub.n_keben == {"一": 1, "二": 1, "口": 1}
    assert _keben_subset(m) is sub and len(m) == 9                 # 缓存；原匹配器没被改


def test_strong_keben_hit_skips_the_font_domain_and_weak_falls_back_to_full(tmp_path, monkeypatch):
    from open_guji_cv.steps.glyph_match import _FontTier, _keben_subset
    m = _matcher(tmp_path, monkeypatch)
    sub = _keben_subset(m)
    tier = _FontTier(m, sub, _FontTier.rule({"cov": None}))
    calls = []
    real = m.match
    monkeypatch.setattr(m, "match", lambda norm, **kw: calls.append(1) or real(norm, **kw))
    kou = m._patches[m._ids.index("kb:053E3")].copy()
    r = tier.match(kou, exclude_id=None)
    assert r.verdict == "same" and r.char == "口" and r.matched_id.startswith("kb:")
    assert calls == [] and (tier.n_query, tier.n_full) == (1, 0)
    yong = m._patches[m._ids.index("font:t:06C38")].copy()           # 刻本库里没有「永」
    r = tier.match(yong, exclude_id=None)
    assert calls == [1] and (tier.n_query, tier.n_full) == (2, 1)
    assert r.to_dict() == real(yong).to_dict() and r.char == "永"
    # min_n：刻本库里不到 2 例的字一律查整库
    tier2 = _FontTier(m, sub, _FontTier.rule({"min_n": 2}))
    tier2.match(kou, exclude_id=None)
    assert tier2.n_full == 1


def test_both_tiers_batched_full_tier_only_computed_for_weak_chunks(tmp_path, monkeypatch):
    """两个开关都开（v0.5.5 缺省）：刻本库、整库两档都走 `_PageBatch`；整库那档按块惰性算，
    一块里没有命中弱的格就不算；两档共用一份查询特征。结果与不合批时相同。"""
    from open_guji_cv.steps.glyph_match import _FontTier, _PageBatch, _keben_subset
    m = _matcher(tmp_path, monkeypatch)
    sub = _keben_subset(m)
    kou = m._patches[m._ids.index("kb:053E3")].copy()
    yong = m._patches[m._ids.index("font:t:06C38")].copy()
    queries = [kou, kou.copy(), yong]
    bsub, bfull = _PageBatch(sub, queries), _PageBatch(m, queries)
    bfull._feats = bsub._feats
    bsub.CHUNK = bfull.CHUNK = 2                                   # 块 0＝两个「口」（强），块 1＝「永」（弱）
    tier = _FontTier(bfull, bsub, _FontTier.rule({"cov": None}))
    plain = _FontTier(m, sub, _FontTier.rule({"cov": None}))
    for q in queries:
        assert tier.match(q, exclude_id=None).to_dict() == plain.match(q, exclude_id=None).to_dict()
    assert (tier.n_query, tier.n_full) == (3, 1)
    assert bfull._c0 == 2                                          # 整库只算了「永」所在的块

def test_strong_rule_on_unsure_needs_cov_and_margin_to_another_char():
    from open_guji_cv.clustering.match import MatchResult
    from open_guji_cv.steps.glyph_match import _FontTier
    t = _FontTier(object(), object(), _FontTier.rule({"family": False}))

    def u(cands, guard=None):
        return MatchResult("unsure", None, None, cands[0][1], 5.0, cands, guard=guard)
    assert t.strong(MatchResult("same", "口", "kb:1", 0.999, 3.0, [("口", 0.999)]))
    assert t.strong(u([("口", 0.985), ("口", 0.984), ("日", 0.95)]))      # 次优同字不算，比异字高 0.035
    assert not t.strong(u([("口", 0.985), ("日", 0.96)]))                  # 分差 0.025 不够
    assert not t.strong(u([("口", 0.975)]))                                # cov 不够
    assert t.strong(u([("口", 0.99)]))                                     # 没有异字：按 0.85 算
    assert not t.strong(u([("口", 0.99)], guard="never_match"))             # 护栏一律算弱
    assert not t.strong(MatchResult("diff", None, None, 0.7, 30.0, [("口", 0.7)]))


def test_family_chars_are_always_weak():
    """字组成员、形近护栏有对手的字：刻本库判 same 也查整库（下游靠字体域给的另一个码位判字）。"""
    from open_guji_cv.clustering.match import MatchResult
    from open_guji_cv.steps.glyph_match import _FontTier, _family_chars
    fam = _family_chars()
    assert {"既", "旣", "一", "二"} <= fam and "口" not in fam
    t = _FontTier(object(), object(), _FontTier.rule(True))
    assert not t.strong(MatchResult("same", "二", "kb:1", 0.999, 3.0, [("二", 0.999)]))
    assert not t.strong(MatchResult("unsure", None, None, 0.985, 5.0, [("既", 0.985)]))
    assert t.strong(MatchResult("same", "口", "kb:1", 0.999, 3.0, [("口", 0.999)]))
