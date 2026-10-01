"""近形决胜（clustering/near_shape.py）：合成字形上的行为契约 + 关闭时逐字节不变。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher, MatchResult
from open_guji_cv.clustering.near_shape import (NearShapeConfig, decide_pair,
                                                trigger_pair)
from open_guji_cv.products.kinds.recog import MatchRec
from open_guji_cv.steps.glyph_match import GlyphMatchParams


def _glyph(rng: np.random.Generator, top: str, jitter: int = 1) -> np.ndarray:
    """64×64 二值「字」：共享的下半部（三横一竖）+ 只在头部不同的部件。
    top="cross" 像「艹」（一横穿两竖），top="dots" 像「业」头（两竖两点、不穿横）。"""
    g = np.zeros((64, 64), np.uint8)
    dy, dx = rng.integers(-jitter, jitter + 1, size=2)
    for y in (30, 40, 50):                       # 共享部件
        g[y:y + 3, 10:54] = 1
    g[28:58, 31:34] = 1
    if top == "cross":
        g[12:15, 8:56] = 1
        g[6:22, 20:23] = 1
        g[6:22, 41:44] = 1
    else:
        g[8:20, 22:25] = 1
        g[8:20, 39:42] = 1
        g[10:14, 12:16] = 1
        g[10:14, 48:52] = 1
        g[19:22, 14:50] = 1
    g = np.roll(np.roll(g, dy, 0), dx, 1)
    noise = rng.random(g.shape) < 0.01           # 刻本斑点
    return (g ^ noise).astype(np.uint8)


def _groups(n=8, seed=0):
    rng = np.random.default_rng(seed)
    return ([_glyph(rng, "cross") for _ in range(n)],
            [_glyph(rng, "dots") for _ in range(n)], rng)


def test_decides_by_the_differing_part_and_finds_the_head_region():
    A, B, rng = _groups()
    for top, want in (("cross", "甲"), ("dots", "乙")):
        d = decide_pair(_glyph(rng, top), A, B, NearShapeConfig(), ("甲", "乙"))
        assert d.reason == "decided" and d.winner == want
        assert d.loo_acc == 1.0
        y0, y1, _, _ = d.region_bbox
        assert y1 <= 32, d.region_bbox          # 差异区域只在头部，不铺到共享的下半部


def test_abstains_when_the_two_groups_are_the_same_shape():
    rng = np.random.default_rng(1)
    A = [_glyph(rng, "cross") for _ in range(8)]
    B = [_glyph(rng, "cross") for _ in range(8)]
    d = decide_pair(_glyph(rng, "cross"), A, B, NearShapeConfig(), ("甲", "乙"))
    assert d.winner is None and d.reason in ("loo", "low_score")


def test_abstains_with_too_few_exemplars():
    A, B, rng = _groups(n=2)
    d = decide_pair(_glyph(rng, "cross"), A, B, NearShapeConfig(), ("甲", "乙"))
    assert d.winner is None and d.reason == "few_exemplars"


def test_outlier_query_is_not_forced_into_the_pair():
    A, B, rng = _groups()
    q = np.zeros((64, 64), np.uint8)
    q[4:60, 4:60] = 1                            # 跟两组都不像（第三个字/残损）
    d = decide_pair(q, A, B, NearShapeConfig(), ("甲", "乙"))
    assert d.winner is None


def test_trigger_rules():
    cfg = NearShapeConfig()
    assert trigger_pair([("甲", 0.98), ("乙", 0.94)], cfg) == (None, None)       # 差够大：不触发
    assert trigger_pair([("甲", 0.98), ("甲", 0.979), ("乙", 0.97)], cfg)[0] == ("甲", "乙")
    assert trigger_pair([("甲", 0.96), ("乙", 0.95)], cfg) == (("甲", "乙"), "cov_low")
    assert trigger_pair([("甲", 0.98), ("乙", 0.975), ("丙", 0.97)], cfg) == (("甲", "乙"), "third_close")


def _matcher(near_shape):
    A, B, _ = _groups(n=6, seed=3)
    m = GlyphMatcher(k=10, near_shape=near_shape)
    for i, g in enumerate(A):
        m.add(f"vol09:1:{i + 1}:1", "甲", g)
    for i, g in enumerate(B):
        m.add(f"vol09:2:{i + 1}:1", "乙", g)
    return m


def test_matcher_off_is_unchanged_and_on_only_reorders_unsure():
    rng = np.random.default_rng(7)
    q = _glyph(rng, "dots")
    off = _matcher(None).match(q)
    on = _matcher(NearShapeConfig()).match(q)
    assert off.near_shape is None and "near_shape" not in off.to_dict()
    assert off == on                             # same 档不碰
    # unsure 档且首选是错的那个字、cov 几乎打平 → 局部决胜把 乙 挪到首位，判档不动
    m = _matcher(NearShapeConfig())
    r0 = MatchResult("unsure", None, None, 0.975, 3.0, [("甲", 0.975), ("乙", 0.972)])
    r = m._apply_near_shape(r0, q, m.extract(q[None])[0], set())
    assert r.near_shape["winner"] == "乙" and r.candidates[0][0] == "乙"
    assert (r.verdict, r.char, r.guard) == ("unsure", None, None)
    # cov 差 ≥ flip_margin 时不许翻盘
    r1 = MatchResult("unsure", None, None, 0.985, 3.0, [("甲", 0.985), ("乙", 0.97)])
    r = m._apply_near_shape(r1, q, m.extract(q[None])[0], set())
    assert r.near_shape["reason"] == "flip_blocked" and r.candidates[0][0] == "甲"


def test_trusted_ids_limit_the_prototypes():
    m = _matcher(NearShapeConfig(cov_min=0.0, margin=1.0))
    m.trusted_ids = {"vol09:1:1:1"}              # 只认一条人裁 → 两组都不够 3 条
    r = m.match(_glyph(np.random.default_rng(8), "dots"))
    assert r.near_shape is None or r.near_shape["reason"] in ("few_exemplars", "cov_low",
                                                              "third_close")


def test_products_and_param_hash_unchanged_when_off():
    rec = MatchRec(id="a:1:1:1", slot=1, verdict="diff")
    assert "near_shape" not in rec.model_dump(mode="json")
    assert MatchRec(id="a:1:1:1", slot=1, verdict="diff",
                    near_shape={"winner": None}).model_dump()["near_shape"] == {"winner": None}
    p = GlyphMatchParams(db_path="x", db_fingerprint="y")
    assert "near_shape" not in p.model_dump(mode="json")
    assert "near_shape" in GlyphMatchParams(db_path="x", db_fingerprint="y",
                                            near_shape=True).model_dump(mode="json")
    assert NearShapeConfig.from_any(None) is None and NearShapeConfig.from_any(False) is None
    assert NearShapeConfig.from_any({"tau": 0.9}).tau == 0.9
    assert isinstance(MatchResult("diff", None, None, 0.0, 0.0).to_dict(), dict)
