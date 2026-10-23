# -*- coding: utf-8 -*-
"""T11 A 档 `witness3_no_diff` 与过切提示 `oversplit_gate="hint"`（GUJI-208cl）。缺省关、关时 params_hash 不变、
关臂字节同。数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _oversplit_hint_pass, _review_lanes_pass

pytestmark = pytest.mark.usefixtures("no_cnn")

B = "tbook:1"
BODY = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜"


# ── 参数：关时不进 dump ────────────────────────────────────────────────

def test_off_keys_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().witness3_no_diff is False and SeedAdmitParams().oversplit_gate == ""
    assert "witness3_no_diff" not in d and not [k for k in d if k.startswith("oversplit_")]
    on = SeedAdmitParams(witness3_no_diff=True, oversplit_gate="hint").model_dump()
    assert on["witness3_no_diff"] is True and on["oversplit_gate"] == "hint"
    assert on["oversplit_short_h_ratio"] == 0.28 and on["oversplit_short_ink"] == 0.16


# ── T11 A 档：witness3 遇库 diff 不放 ─────────────────────────────────

def _w_page(chars, slot=5):
    recs = []
    for i, ch in enumerate(chars, 1):
        if i == slot:
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=False, char="天",
                                 doubts=["replace_align", "库 diff(cov=0.8)"], evidence={}))
        else:
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=True, channel="match_ref", char=ch))
    return [ColumnAdmit(col=1, chars=recs)]


def _w_run(verdict, guard=None, **params):
    chars = BODY[:30]
    out = _w_page(chars)
    wit = lambda n: NS(name=n, text="前" + chars[:4] + "天" + chars[5:] + "後",
                       index=build_ngram_index("前" + chars[:4] + "天" + chars[5:] + "後"))
    mm = {f"{B}:1:5": NS(char=None, candidates=[("大", 0.8)], guard=guard, verdict=verdict)}
    p = SeedAdmitParams(db_path="x", lane_witness3=True, **params)
    n = _review_lanes_pass(p, out, mm, {f"{B}:1:5": ("天", "replace")}, {f"{B}:1:5": "天"}, VariantMap.load(None),
                           lambda: [wit("d.txt"), wit("w.txt"), wit("y.txt")])
    return n, out[0].chars[4]


def test_w3_off_releases_even_when_diff():
    n, r = _w_run("diff")
    assert n == 1 and r.admit and r.channel == "witness3"


def test_w3_on_diff_stays_pending_with_doubt():
    n, r = _w_run("diff", witness3_no_diff=True)
    assert n == 0 and not r.admit and r.channel is None
    assert "witness3_diff" in r.doubts and r.evidence["lane_skip"]["why"] == "lib_diff"


@pytest.mark.parametrize("verdict", ["unsure", "same", None])
def test_w3_on_non_diff_still_released(verdict):
    n, r = _w_run(verdict, witness3_no_diff=True)
    assert n == 1 and r.admit and r.channel == "witness3" and r.char == "天"


def test_w3_on_does_not_touch_other_lanes():
    """开关只管 witness3：同一格 verdict=diff 时 admit 集合 = 关臂 − witness3 那格。"""
    off = _w_run("diff")[1]
    on = _w_run("diff", witness3_no_diff=True)[1]
    assert off.admit and not on.admit and off.char == on.char == "天"


# ── 过切提示：几何 ────────────────────────────────────────────────────

def _c(cid, idx, h, *, w=100.0, ink=0.3, flags=(), sub=None, kind="char", cell_type="char"):
    return NS(id=cid, idx=idx, height=float(h), width=float(w), ink_ratio=ink, flags=list(flags), sub=sub,
              step3_kind=kind, cell_type=cell_type)


def _filler(col, n=24, start=0):
    return [_c(f"f{col}:{i}", start + i, 100) for i in range(n)]


def _idx(cols):
    return NS(columns=[NS(col=k, chars=v) for k, v in cols.items()])


def _out(ids, admit):
    return [ColumnAdmit(col=1, chars=[AdmitRec(id=i, slot=n, admit=admit.get(i, False), channel="match_ref" if admit.get(i) else None,
                                               char="字", doubts=[]) for n, i in enumerate(ids, 1)])]


def _hint(cols, admit=None, **kw):
    ci = _idx(cols)
    ids = [c.id for v in cols.values() for c in v if not c.id.startswith("f")]
    out = _out(ids, admit or {})
    n = _oversplit_hint_pass(SeedAdmitParams(db_path="x", oversplit_gate="hint", **kw), out, ci)
    return n, {r.id: r for r in out[0].chars}


def _pair(a=55, b=50, **kw):
    return _c("a", 0, a, **kw), _c("b", 1, b)


def test_hint_pair_hits_pending_both_cells():
    a, b = _pair()
    n, rs = _hint({1: [a, b], 2: _filler(2)})
    assert n == 2
    for k in ("a", "b"):
        assert "oversplit_pair" in rs[k].doubts and rs[k].evidence["oversplit"]["partner"] in ("a", "b")
        assert not rs[k].admit


def test_hint_only_on_pending_release_set_unchanged():
    a, b = _pair()
    n, rs = _hint({1: [a, b], 2: _filler(2)}, admit={"a": True})
    assert n == 1 and rs["a"].admit and rs["a"].doubts == [] and "oversplit_pair" in rs["b"].doubts


def test_hint_both_released_gives_no_hint():          # vol05:123:9:9/10 容忍误报：双放行 → 0 提示
    a, b = _pair()
    n, rs = _hint({1: [a, b], 2: _filler(2)}, admit={"a": True, "b": True})
    assert n == 0 and all(r.doubts == [] for r in rs.values())


def test_hint_red_line_cells_unchanged():             # 红线：已放行的半字格（vol02:15:9:20 型）不被提示、不被降级
    a, b = _pair()
    n, rs = _hint({1: [a, b], 2: _filler(2)}, admit={"a": True, "b": True})
    assert all(r.admit for r in rs.values())


@pytest.mark.parametrize("kw", [dict(flags=["seal_region"]), dict(ink=0.1)])
def test_hint_exclusions_seal_and_short_ink(kw):
    s = _c("a", 0, 50, **kw)                     # 较矮者带 seal_region／低墨量
    n, _ = _hint({1: [s, _c("b", 1, 55)], 2: _filler(2)})
    assert n == 0


def test_hint_exclusion_single_stroke_short_ratio():  # 较矮者 ≤0.28 中位高 → 单笔横画，不提
    n, _ = _hint({1: [_c("a", 0, 28), _c("b", 1, 74)], 2: _filler(2)})
    assert n == 0


def test_hint_cross_column_not_paired():
    n, _ = _hint({1: [_c("a", 0, 55)], 2: [_c("b", 0, 50)] + _filler(2, start=1), 3: _filler(3)})
    assert n == 0


def test_hint_non_adjacent_idx_not_paired():
    n, _ = _hint({1: [_c("a", 0, 55), _c("b", 2, 50)], 2: _filler(2)})
    assert n == 0


def test_hint_annotation_and_non_char_not_paired():
    n, _ = _hint({1: [_c("a", 0, 55, sub="a"), _c("b", 1, 50)], 2: _filler(2)})
    assert n == 0
    n, _ = _hint({1: [_c("a", 0, 55, kind="jiazhu"), _c("b", 1, 50)], 2: _filler(2)})
    assert n == 0


def test_hint_page_with_fewer_than_20_body_cells_skipped():
    a, b = _pair()
    n, _ = _hint({1: [a, b] + [_c(f"g{i}", 2 + i, 100) for i in range(10)]})
    assert n == 0


def test_hint_sum_out_of_range_not_paired():
    n, _ = _hint({1: [_c("a", 0, 40), _c("b", 1, 40)], 2: _filler(2)})      # 和 0.8 → 恰在下限内？ 80 ≥ 80
    assert n == 2
    n, _ = _hint({1: [_c("a", 0, 30), _c("b", 1, 40)], 2: _filler(2)})      # 和 70 < 80
    assert n == 0


def test_hint_thresholds_are_params():
    a, b = _pair(55, 50)
    n, _ = _hint({1: [a, b], 2: _filler(2)}, oversplit_sum_hi=1.0)
    assert n == 0


def test_hint_no_char_index_abstains():
    out = _out(["a"], {})
    assert _oversplit_hint_pass(SeedAdmitParams(db_path="x", oversplit_gate="hint"), out, None) == 0


# ── 整步：关臂字节同；开臂放行集同 ─────────────────────────────────────

def _step_run(tmp_path, monkeypatch, params, chars_idx):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    ctx = RunContext(make_book("tbook"), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    chars = ["山", "水", "木"]
    recs = [dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="山", candidates=[("山", 1.0)]),
            dict(slot=2, verdict="diff", cov=0.2, wmax=0.0, char=None, candidates=[("田", 0.2)]),
            dict(slot=3, verdict="diff", cov=0.2, wmax=0.0, char=None, candidates=[("田", 0.2)])]
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(1, "tbook", recs=recs, col=1))
    write_product(ctx, "align_ref", 1, align_ref=page_align_ref(
        1, "tbook", recs=[dict(slot=i + 1, align_char=c) for i, c in enumerate(chars)], col=1))
    real = sa._opt
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: chars_idx if k == "char_index" else real(c, k, pg))
    return STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"]


def test_step_off_arm_byte_identical_and_hint_keeps_release_set(tmp_path, monkeypatch):
    ci = NS(columns=[NS(col=1, chars=[_c("tbook:1:1:1", 0, 100), _c("tbook:1:1:2", 1, 55), _c("tbook:1:1:3", 2, 50)]
                        + [_c(f"x{i}", 3 + i, 100) for i in range(22)])])
    base = _step_run(tmp_path / "a", monkeypatch, SeedAdmitParams(), ci)
    off = _step_run(tmp_path / "b", monkeypatch, SeedAdmitParams(oversplit_gate="", witness3_no_diff=False), ci)
    assert base.model_dump_json() == off.model_dump_json()
    on = _step_run(tmp_path / "c", monkeypatch, SeedAdmitParams(oversplit_gate="hint"), ci)
    adm = lambda pg: [(r.id, r.admit, r.channel, r.char) for cc in pg.columns for r in cc.chars]
    assert adm(base) == adm(on)
    hit = [r.id for cc in on.columns for r in cc.chars if "oversplit_pair" in r.doubts]
    assert hit and all(not r.admit for cc in on.columns for r in cc.chars if r.id in hit)


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
