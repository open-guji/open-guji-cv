# -*- coding: utf-8 -*-
"""Step7 待审补放三通道（overview#433，R2 道）：R1 `witness3`、R4 `coord_fallback`、R5 `seal`。

直接测页末那一遍 `_review_lanes_pass`（只吃已写好的 AdmitRec ＋ 库/对齐/坐标/证人），证人逐格读法
测 `clustering.witness_cells`。数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.clustering.witness_cells import witness_readings
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.review.cards import card_class
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _lane_class, _review_lanes_pass

pytestmark = pytest.mark.usefixtures("no_cnn")   # CNN 通道开不开随环境变，钉成关（overview#407）

B = "tbook:1"
BODY = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜"


def _vm():
    return VariantMap.load(None)


def _wit(name, text):
    return NS(name=name, text=text, index=build_ngram_index(text))


def _page(chars, pending: dict):
    """一列，`chars` 是整列的字；`pending={slot: dict(doubts=…, char=…, evidence=…)}` 的格待审，其余已放行。"""
    recs = []
    for i, ch in enumerate(chars, 1):
        if i in pending:
            pd = pending[i]
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=False, char=pd.get("char", ch),
                                 doubts=list(pd.get("doubts", [])), evidence=dict(pd.get("evidence", {}))))
        else:
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=True, channel="match_ref", char=ch))
    return [ColumnAdmit(col=1, chars=recs)]


def _mm(lib: dict, guard: dict | None = None):
    return {f"{B}:1:{s}": NS(char=None, candidates=[(c, 0.95)], guard=(guard or {}).get(s)) for s, c in lib.items()}


def _run(out, *, lib=None, amap=None, coord=None, wits=(), guard=None, **params):
    p = SeedAdmitParams(db_path="x", **params)
    n = _review_lanes_pass(p, out, _mm(lib or {}, guard), amap or {}, coord or {}, _vm(),
                           (lambda: list(wits)) if wits else None)
    return n, {r.slot: r for r in out[0].chars}


def _ids(d):
    return {f"{B}:1:{s}": v for s, v in d.items()}


# ── 证人逐格读法 ──────────────────────────────────────────────────────

def test_witness_readings_equal_and_replace():
    """锚上之后 equal 段逐位配；等长 replace 段（我们认错的那一位）配证人原字。"""
    seq = [(f"c{i}", ch) for i, ch in enumerate(BODY[:30])]
    seq[10] = ("c10", "口")                       # 我们这一位认成了別的字
    w = "序言若干字" + BODY + "跋尾"
    got = witness_readings(seq, w, build_ngram_index(w))
    assert got["c0"] == "天" and got["c29"] == BODY[29]
    assert got["c10"] == BODY[10]


def test_witness_readings_unanchored_is_empty():
    seq = [(f"c{i}", ch) for i, ch in enumerate(BODY[:30])]
    w = "毫不相干的一段文字" * 5
    assert witness_readings(seq, w, build_ngram_index(w)) == {}


# ── 类别镜像 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("doubts,ev,char,ref,lib", [
    (["replace_align"], {}, "天", "天", "大"),
    (["context_vs_ref", "replace_align"], {}, "天", "天", "大"),
    (["near_form", "库里没有这个字"], {}, "天", "天", "夭"),
    (["库里没有这个字", "replace_align"], {}, "天", "天", None),
    (["variant_indirect"], {}, "天", "天", "天"),
    (["occluded"], {"occluded": {"via": "coord"}}, "天", None, None),
    (["form_open"], {}, None, "天", "天"),
    (["库 unsure(cov=0.9)"], {}, "已", "已", "巳"),
    (["库 unsure(cov=0.9)", "shadow_veto"], {}, "天", None, "天"),
])
def test_lane_class_mirrors_card_class(doubts, ev, char, ref, lib):
    assert _lane_class(doubts, ev, char, ref, lib) == card_class(doubts, ev, char=char, ref_char=ref, lib_top=lib)


# ── R1 三证人一致 ──────────────────────────────────────────────────────

def _r1_setup(lib_char="大", wit_char=None, coord_char="天"):
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["replace_align", "库 unsure(cov=0.93)"], char="天")})
    chars5 = chars[:4] + (wit_char or "天") + chars[5:]
    wits = [_wit("d.txt", "前" + chars5 + "後"), _wit("w.txt", "前" + chars5 + "後"),
            _wit("y.txt", "前" + chars5 + "後")]
    return out, dict(lib={5: lib_char}, amap=_ids({5: ("天", "replace")}), coord=_ids({5: coord_char}), wits=wits)


def test_r1_off_by_default():
    out, kw = _r1_setup()
    n, rs = _run(out, **kw)
    assert n == 0 and not rs[5].admit


def test_r1_all_agree_admits_ref_char_text_only():
    out, kw = _r1_setup()
    n, rs = _run(out, lane_witness3=True, **kw)
    r = rs[5]
    assert n == 1 and r.admit and r.char == "天" and r.channel == r.provenance == "witness3"
    assert r.doubts == ["lane_witness3"] and r.evidence["no_glyph_lib"] is True
    assert r.evidence["lane"]["prev_doubts"][0] == "replace_align"
    assert set(r.evidence["lane"]["witnesses"].values()) == {"天"}


def test_r1_one_witness_differs_stays():
    out, kw = _r1_setup()
    kw["wits"][2] = _wit("y.txt", "前" + BODY[:4] + "夫" + BODY[5:30] + "後")
    n, rs = _run(out, lane_witness3=True, **kw)
    assert n == 0 and not rs[5].admit


def test_r1_coord_differs_stays():
    out, kw = _r1_setup(coord_char="夫")
    n, _ = _run(out, lane_witness3=True, **kw)
    assert n == 0


def test_r1_lib_variant_of_ref_stays():
    """刻本原字（库首位）与整理本字是已知异体对：不改刻本形，送审。"""
    vm = _vm()
    a, b = next((x, y) for x, y in (("獘", "弊"), ("峯", "峰"), ("羣", "群")) if vm.semantic(x) == vm.semantic(y))
    chars = BODY[:4] + b + BODY[5:30]
    out = _page(chars, {5: dict(doubts=["replace_align"], char=b)})
    wits = [_wit(f"{k}.txt", "前" + chars + "後") for k in "dwy"]
    n, rs = _run(out, lane_witness3=True, lib={5: a}, amap=_ids({5: (b, "replace")}),
                 coord=_ids({5: b}), wits=wits)
    assert n == 0 and not rs[5].admit and rs[5].evidence["lane_skip"]["why"] == "lib_variant"


def test_r1_needs_replace_op_and_r1_class():
    out, kw = _r1_setup()
    kw["amap"] = _ids({5: ("天", "equal")})
    assert _run(out, lane_witness3=True, **kw)[0] == 0
    out, kw = _r1_setup()
    out[0].chars[4].doubts = ["replace_align", "variant_indirect", "库里没有这个字"]   # 归「库里没有」
    assert _run(out, lane_witness3=True, **kw)[0] == 0


def test_lanes_skip_ji_yi_si_family():
    chars = BODY[:4] + "已" + BODY[5:30]
    out = _page(chars, {5: dict(doubts=["replace_align"], char="已")})
    wits = [_wit(f"{k}.txt", "前" + chars + "後") for k in "dwy"]
    n, _ = _run(out, lane_witness3=True, lane_coord=True, lib={5: "已"},
                amap=_ids({5: ("已", "replace")}), coord=_ids({5: "已"}), wits=wits)
    assert n == 0


def test_garbled_column_skipped_whole():
    """同列有一格被 #427 乱码护栏拦过，整列不走 R1/R4。"""
    out, kw = _r1_setup()
    out[0].chars[20].admit = False
    out[0].chars[20].doubts = ["ctx_garble_shape"]
    n, rs = _run(out, lane_witness3=True, **kw)
    assert n == 0 and not rs[5].admit


# ── R4 坐标对位兜底 ────────────────────────────────────────────────────

def _r4(lib_char, coord_char, wit_chars, guard=None, **params):
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", "上下文 margin 不足(0.10)"], char=lib_char)})
    wits = [_wit(f"{k}.txt", "前" + chars[:4] + c + chars[5:] + "後") for k, c in zip("dwy", wit_chars)]
    return _run(out, lib={5: lib_char}, coord=_ids({5: coord_char}), wits=wits,
                guard=({5: guard} if guard else None), **params)


def test_r4_lib_coord_primary_agree():
    n, rs = _r4("天", "天", "天夫夫", lane_coord=True)
    assert n == 1 and rs[5].char == "天" and rs[5].channel == "coord_fallback"
    assert rs[5].evidence["lane"]["via"] == "lib_coord_primary" and rs[5].doubts == ["lane_coord_fallback"]


def test_r4_all_witnesses_and_coord_agree_without_lib():
    n, rs = _r4("夫", "天", "天天天", lane_coord=True)
    assert n == 1 and rs[5].char == "天" and rs[5].evidence["lane"]["via"] == "witnesses_coord"


def test_r4_lib_guard_blocks_witness_branch():
    n, _ = _r4("夫", "天", "天天天", guard="conflict", lane_coord=True)
    assert n == 0


def test_r4_partial_agreement_stays():
    n, _ = _r4("夫", "天", "天天夫", lane_coord=True)
    assert n == 0


def test_r4_only_other_class():
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["near_form"], char="天")})
    wits = [_wit(f"{k}.txt", "前" + chars + "後") for k in "dwy"]
    n, _ = _run(out, lane_coord=True, lib={5: "天"}, coord=_ids({5: "天"}), wits=wits)
    assert n == 0


# ── R5 印章区 ─────────────────────────────────────────────────────────

def _seal(cells, coord=None, **params):
    """`cells={slot: (默认字, via)}` 是遮挡格。"""
    chars = BODY[:20]
    pend = {s: dict(doubts=["occluded"], char=c,
                    evidence={"occluded": {"density": 9.0, "via": via, **({"ref_blank": True} if via == "coord_blank" else {})}})
            for s, (c, via) in cells.items()}
    return _run(_page(chars, pend), coord=_ids(coord or {}), **params)


def test_r5_coord_char_admitted_and_blank_is_nonchar():
    n, rs = _seal({3: ("黃", "coord"), 4: (None, "coord_blank"), 5: ("宇", "align"), 6: (None, "none")},
                  coord={3: "黃", 4: ""}, lane_seal=True)
    assert n == 2
    assert rs[3].admit and rs[3].char == "黃" and rs[3].channel == "seal" and rs[3].doubts == ["lane_seal"]
    assert rs[4].admit and rs[4].char is None and rs[4].evidence["lane"]["nonchar"] is True
    assert not rs[5].admit and not rs[6].admit


def test_r5_align_via_opt_in():
    n, rs = _seal({5: ("宇", "align")}, lane_seal=True, lane_seal_via="coord,align")
    assert n == 1 and rs[5].char == "宇"


def test_r5_title_column_blocked():
    """卷端／版心题列（坐标对位连起来含「總目」）整列不放。"""
    n, _ = _seal({1: ("書", "coord"), 2: ("總", "coord")}, coord={1: "書", 2: "總", 3: "目"}, lane_seal=True)
    assert n == 0


def test_human_and_excluded_untouched():
    out, kw = _r1_setup()
    out[0].chars[4].channel = "human"
    assert _run(out, lane_witness3=True, **kw)[0] == 0
    out, kw = _r1_setup()
    out[0].chars[4].doubts = ["excluded"]
    assert _run(out, lane_witness3=True, **kw)[0] == 0


# ── 开关与指纹 ────────────────────────────────────────────────────────

def test_params_off_not_in_dump():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert not any(k.startswith("lane_") for k in d)
    d = SeedAdmitParams(db_path="x", lane_seal=True).model_dump()
    assert d["lane_seal"] is True and "lane_witness_fingerprint" in d


def test_slots_skip_seal_nonchar():
    from open_guji_cv.report.slots import _to_slot
    rec = AdmitRec(id=f"{B}:1:4", slot=4, admit=True, channel="seal", char=None, doubts=["lane_seal"],
                   evidence={"occluded": {"via": "coord_blank", "ref_blank": True}})
    s = _to_slot("tbook", 1, 1, rec, None)
    assert s.excluded and not s.unreadable


# ── 三通道统一异体护栏（#433 vol04：coord_fallback 把刻本「㫖」放成「旨」）──────────────

def test_lane_variant_guard_blocks_when_candidate_is_variant():
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", "上下文 margin 不足(0.10)"], char="旨")})
    wits = [_wit(f"{k}.txt", "前" + chars[:4] + "旨" + chars[5:] + "後") for k in "dwy"]
    p = SeedAdmitParams(db_path="x", lane_coord=True)
    mm = {f"{B}:1:5": NS(char=None, candidates=[("旨", 0.95), ("㫖", 0.94)], guard=None)}
    n = _review_lanes_pass(p, out, mm, {}, _ids({5: "旨"}), _vm(), lambda: wits)
    r = out[0].chars[4]
    assert n == 0 and not r.admit
    assert r.evidence["lane_skip"]["why"] == "cand_variant" and r.evidence["lane_skip"]["form"] == "㫖"


def test_lane_variant_guard_off_restores_old_behaviour():
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", "上下文 margin 不足(0.10)"], char="旨")})
    wits = [_wit(f"{k}.txt", "前" + chars[:4] + "旨" + chars[5:] + "後") for k in "dwy"]
    p = SeedAdmitParams(db_path="x", lane_coord=True, lane_variant_guard=False)
    mm = {f"{B}:1:5": NS(char=None, candidates=[("旨", 0.95), ("㫖", 0.94)], guard=None)}
    n = _review_lanes_pass(p, out, mm, {}, _ids({5: "旨"}), _vm(), lambda: wits)
    assert n == 1 and out[0].chars[4].char == "旨"
