# -*- coding: utf-8 -*-
"""T11 A 档 `witness3_no_diff`（GUJI-208cl）。缺省关、关时 params_hash 不变、关臂字节同。数据全是自造的。
（同文件原有的过切提示 `oversplit_gate` 已于 2026-10-23 删除，见 doc/exp/准入三闸-vol05-vol09-报告.md。）"""
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
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _review_lanes_pass

pytestmark = pytest.mark.usefixtures("no_cnn")

B = "tbook:1"
BODY = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜"


# ── 参数：关时不进 dump ────────────────────────────────────────────────

def test_off_keys_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().witness3_no_diff is False
    assert "witness3_no_diff" not in d
    assert SeedAdmitParams(witness3_no_diff=True).model_dump()["witness3_no_diff"] is True


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


# ── 整步：关臂字节同 ─────────────────────────────────────

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


def test_step_off_arm_byte_identical(tmp_path, monkeypatch):
    base = _step_run(tmp_path / "a", monkeypatch, SeedAdmitParams(), None)
    off = _step_run(tmp_path / "b", monkeypatch, SeedAdmitParams(witness3_no_diff=False), None)
    assert base.model_dump_json() == off.model_dump_json()


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
