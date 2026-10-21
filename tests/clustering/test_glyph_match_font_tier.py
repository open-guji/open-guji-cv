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


def test_font_tier_is_off_by_default_and_out_of_the_params_hash():
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    off = GlyphMatchParams(db_path="x.db", db_fingerprint="f", borrow_fingerprint="")
    assert off.font_tier is None and "font_tier" not in off.model_dump(mode="json")
    assert "font_tier" not in off.model_copy(update={"font_tier": False}).model_dump(mode="json")
    on = off.model_copy(update={"font_tier": {"cov": 0.99}})
    assert on.model_dump(mode="json")["font_tier"] == {"cov": 0.99}
    assert params_hash(on) != params_hash(off)


def test_rule_defaults_and_unknown_keys():
    from open_guji_cv.steps.glyph_match import _FontTier
    assert _FontTier.rule(None) is None and _FontTier.rule(False) is None
    assert _FontTier.rule(True) == {"cov": None, "margin": 0.03, "min_n": 0, "same": True,
                                    "seed": None, "seed_k": 20, "emb": None}
    assert _FontTier.rule({"cov": 0.99})["cov"] == 0.99
    with pytest.raises(ValueError):
        _FontTier.rule({"covv": 0.99})
    with pytest.raises(ValueError):
        _FontTier.rule({"seed": "near"})


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
    tier = _FontTier(m, sub, _FontTier.rule(True))
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


def test_seed_mode_compares_only_the_seeded_font_rows(tmp_path, monkeypatch):
    """`seed: cnn`：命中弱的格只比种子字的字体行。CNN 与向量包换成假的：种子里有「永」就认得出，没有就认不出。"""
    import numpy as np
    from open_guji_cv.steps import glyph_match as GM
    m = _matcher(tmp_path, monkeypatch)
    m.k = 2
    sub = GM._keben_subset(m)
    yong = m._patches[m._ids.index("font:t:06C38")].copy()
    full = m.match(yong)
    assert full.verdict == "same" and full.char == "永"

    class FakeCnn:
        def embed(self, norms):
            return np.array([[1.0, 0.0]], np.float32)

    for seeds, expect_yong in ((["永", "山"], True), (["日", "山"], False)):
        chars = seeds + ["一", "二", "口"]
        M = np.array([[1.0, 0.0]] * len(seeds) + [[0.0, 1.0]] * 3, np.float32)
        monkeypatch.setattr(GM, "_SEED", {"cnn": FakeCnn(), "M": M, "chars": chars})
        tier = GM._FontTier(m, sub, GM._FontTier.rule({"seed": "cnn", "seed_k": len(seeds), "same": False}))
        r = tier.match(yong, exclude_id=None)
        assert tier.n_full == 1
        assert (r.char == "永") is expect_yong
        if expect_yong:
            assert r.to_dict() == full.to_dict()


def test_seed_mode_records_the_emb_version_in_the_params(monkeypatch):
    from open_guji_cv.clustering import emb_pack
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    monkeypatch.setattr(emb_pack, "current_spec", lambda: {"ckpt_fp": "a", "font_fp": "b", "code_fp": "c", "extra": []})
    p = GlyphMatchParams(db_path="x.db", db_fingerprint="f", borrow_fingerprint="", font_tier={"seed": "cnn"})
    assert p.font_tier["emb"].startswith("emb-")
    assert p.model_dump(mode="json")["font_tier"]["emb"] == p.font_tier["emb"]
