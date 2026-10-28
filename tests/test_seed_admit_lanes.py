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


@pytest.mark.parametrize("doubt", ["ctx_guard_ref", "group_flow_ref_dissent", "group_flow_coord_dissent"])
def test_r4_keeps_ref_review_cells(doubt):
    """护栏拿整理本字拦下的格（vol20 45:5:18 諸→諧）不再按整理本字放回；开关可关。"""
    chars = BODY[:30]
    def run(**params):
        out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", doubt], char="夫")})
        wits = [_wit(f"{k}.txt", "前" + chars[:4] + "天" + chars[5:] + "後") for k in "dwy"]
        return _run(out, lib={5: "夫"}, coord=_ids({5: "天"}), wits=wits, lane_coord=True, **params)
    n, rs = run()
    assert n == 0 and not rs[5].admit
    n, rs = run(lane_keep_ref_review=False)
    assert n == 1 and rs[5].char == "天"


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
                  coord={3: "黃", 4: ""}, lane_seal=True, lane_seal_via="coord")
    assert n == 2
    assert rs[3].admit and rs[3].char == "黃" and rs[3].channel == "seal" and rs[3].doubts == ["lane_seal"]
    assert rs[4].admit and rs[4].char is None and rs[4].evidence["lane"]["nonchar"] is True
    assert not rs[5].admit and not rs[6].admit


def test_r5_align_via_opt_in():
    n, rs = _seal({5: ("宇", "align")}, lane_seal=True, lane_seal_via="coord,align")
    assert n == 1 and rs[5].char == "宇"


def test_r5_align_via_on_by_default():
    """2026-10-26 起 `lane_seal_via` 缺省 coord,align（A32 印章格研究）。"""
    n, rs = _seal({5: ("宇", "align")}, lane_seal=True)
    assert n == 1 and rs[5].char == "宇"


def _title_col(text, cells, lib=None, **params):
    """第 1 列坐标对位整串是 `text`；`cells={slot: 默认字}` 是遮挡格（via=coord）。"""
    chars = text + BODY[len(text):20]
    pend = {s: dict(doubts=["occluded"], char=c, evidence={"occluded": {"density": 9.0, "via": "coord"}})
            for s, c in cells.items()}
    coord = {i: ch for i, ch in enumerate(text, 1)}
    coord.update({i: "" for i in range(len(text) + 1, 21)})
    return _run(_page(chars, pend), coord=_ids(coord), lib=lib, lane_seal=True, **params)


def test_r5_title_formula_admits_and_normalizes_juan():
    """题列套语「欽定四庫全書總目卷N」：整列印章格放行，「巻」写成「卷」，库否决、异体护栏都不管。"""
    text = "欽定四庫全書總目巻十四"
    cells = {i: ch for i, ch in enumerate(text, 1)}
    n, rs = _title_col(text, cells, lib={1: "藏", 9: "卷"})
    assert n == len(text)
    assert rs[1].admit and rs[1].char == "欽" and rs[1].evidence["lane"]["title_formula"] is True
    assert rs[9].char == "卷" and rs[9].evidence["lane"]["norm_from"] == "巻"
    n, rs = _title_col(text, cells, lane_seal_title_norm="")
    assert rs[9].char == "巻"


def test_r5_title_formula_needs_whole_column_match():
    """坐标对位只对上半列（vol36 p2：錄····書總目卷七十一）不是套语，仍按题列整列拦。"""
    n, _ = _title_col("錄書總目卷七十一", {1: "錄", 2: "書"})
    assert n == 0
    n, _ = _title_col("欽定四庫全書總目卷十四", {1: "欽"}, lane_seal_title_formula="")
    assert n == 0


def test_r5_body_column_with_zongmu_not_title():
    """正文里的「崇文總目」不再让整列不走 R5。"""
    n, rs = _title_col("所註存崇文總目稱其", {4: "崇", 5: "文"})
    assert n == 2 and rs[4].char == "崇"


def test_r5_lib_veto():
    """库首位覆盖度 ≥0.95、与默认字不同 → 不放，记 lane_skip。"""
    n, rs = _seal({3: ("兀", "coord")}, coord={3: "兀"}, lane_seal=True, lib={3: "元"})
    assert n == 0 and rs[3].evidence["lane_skip"]["why"] == "lib_veto"
    n, rs = _seal({3: ("兀", "coord")}, coord={3: "兀"}, lane_seal=True, lib={3: "元"}, lane_seal_lib_veto=0)
    assert n == 1
    n, rs = _seal({3: ("兀", "coord")}, coord={3: "兀"}, lane_seal=True, lib={3: "元"}, lane_seal_lib_veto=0.99)
    assert n == 1                     # 覆盖度 0.95 < 0.99


def test_r5_page_shift_guard():
    """默认字整体错一格（库读出的字都等于下一格的默认字）→ 本页印章格一律不放。"""
    text = "漢官舊儀一卷補遺一卷"
    cells = {i: (ch, "coord") for i, ch in enumerate(text, 1)}
    lib = {i: text[i] for i in range(1, len(text))}        # 第 i 格图上是第 i+1 个字
    n, rs = _seal(cells, coord={i: ch for i, ch in enumerate(text, 1)}, lane_seal=True, lib=lib)
    assert n == 0 and rs[1].evidence["lane_skip"]["why"] == "page_shift"
    n, _ = _seal(cells, coord={i: ch for i, ch in enumerate(text, 1)}, lane_seal=True, lib=lib,
                 lane_seal_shift_guard=False, lane_seal_lib_veto=0)
    assert n == len(text)
    lib_ok = {i: ch for i, ch in enumerate(text, 1)}
    n, _ = _seal(cells, coord={i: ch for i, ch in enumerate(text, 1)}, lane_seal=True, lib=lib_ok)
    assert n == len(text)


def test_r5_title_column_blocked():
    """卷端／版心题列（坐标对位连起来含「總目」）整列不放。"""
    n, _ = _seal({1: ("書", "coord"), 2: ("總", "coord")}, coord={1: "書", 2: "總", 3: "目"}, lane_seal=True)
    assert n == 0


# ── R5 补充：库首位同字当第二证据（seal_lib_agree，overview#471 去章）──────────

def test_seal_lib_agree_off_by_default():
    n, _ = _seal({1: ("書", "coord")}, coord={1: "書", 2: "總", 3: "目"}, lane_seal=True)
    assert n == 0
    n, _ = _seal({5: ("宇", "align")}, lane_seal=True, lane_seal_via="coord")
    assert n == 0


def test_seal_lib_agree_passes_title_column_and_align_via():
    cells = {1: ("書", "coord"), 2: ("總", "coord"), 5: ("宇", "align")}
    coord = {1: "書", 2: "總", 3: "目"}
    chars = BODY[:20]
    pend = {s: dict(doubts=["occluded"], char=c, evidence={"occluded": {"density": 9.0, "via": v}})
            for s, (c, v) in cells.items()}
    out = _page(chars, pend)
    n, rs = _run(out, coord=_ids(coord), lane_seal=True, seal_lib_agree=True,
                 lib={1: "書", 2: "他", 5: "宇"})
    assert n == 2
    assert rs[1].admit and rs[1].char == "書" and rs[1].channel == "seal"
    assert rs[1].evidence["lane"]["lib_agree"] == 0.95
    assert not rs[2].admit            # 库首位不同字：照旧送审（题列仍整列拦）
    assert rs[5].admit and rs[5].char == "宇"


def test_seal_lib_agree_needs_cov_and_keeps_guards():
    pend = {1: dict(doubts=["occluded"], char="書", evidence={"occluded": {"density": 9.0, "via": "coord"}})}
    n, _ = _run(_page(BODY[:20], pend), coord=_ids({1: "書", 2: "總", 3: "目"}), lane_seal=True,
                seal_lib_agree=True, seal_lib_cov=0.99, lib={1: "書"})
    assert n == 0                     # 库覆盖度 0.95 < 0.99
    jys = {1: dict(doubts=["occluded"], char="己", evidence={"occluded": {"density": 9.0, "via": "coord"}})}
    n, _ = _run(_page("己" + BODY[1:20], jys), coord=_ids({1: "己"}), lane_seal=True, seal_lib_agree=True, lib={1: "己"})
    assert n == 0                     # 己已巳一族不走


def test_seal_lib_agree_off_not_in_dump():
    d = SeedAdmitParams(db_path="x", lane_seal=True).model_dump()
    assert "seal_lib_agree" not in d and "seal_lib_cov" not in d
    d = SeedAdmitParams(db_path="x", lane_seal=True, seal_lib_agree=True).model_dump()
    assert d["seal_lib_agree"] is True and d["seal_lib_cov"] == 0.9


def test_human_and_excluded_untouched():
    out, kw = _r1_setup()
    out[0].chars[4].channel = "human"
    assert _run(out, lane_witness3=True, **kw)[0] == 0
    out, kw = _r1_setup()
    out[0].chars[4].doubts = ["excluded"]
    assert _run(out, lane_witness3=True, **kw)[0] == 0


# ── 开关与指纹 ────────────────────────────────────────────────────────

def test_params_off_not_in_dump():
    d = SeedAdmitParams(db_path="x", lane_seal=False).model_dump()
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



# ── lane_variant_keep_rare（A24 10-24，vol11–20：整理本照录刻本异体、库首位同形，却被异体护栏拦）──────

def _keep_rare(char, cands, **params):
    chars = BODY[:30]
    out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", "上下文 margin 不足(0.10)"], char=char)})
    wits = [_wit(f"{k}.txt", "前" + chars[:4] + char + chars[5:] + "後") for k in "dwy"]
    p = SeedAdmitParams(db_path="x", lane_coord=True, **params)
    mm = {f"{B}:1:5": NS(char=None, candidates=cands, guard=None)}
    n = _review_lanes_pass(p, out, mm, {}, _ids({5: char}), _vm(), lambda: wits)
    return n, out[0].chars[4]


def test_keep_rare_admits_rare_variant_agreed_by_lib_and_coord():
    n, r = _keep_rare("䘮", [("䘮", 0.989), ("喪", 0.955)])
    assert n == 1 and r.admit and r.char == "䘮" and r.channel == "coord_fallback"
    assert r.evidence["lane"]["keep_rare"] == "喪"


def test_keep_rare_does_not_turn_rare_variant_into_common_form():
    # 放的是通用字（喪）、候选里有刻本异体（䘮）：照旧拦——这正是 #433 护栏要防的
    n, r = _keep_rare("喪", [("喪", 0.95), ("䘮", 0.94)])
    assert n == 0 and not r.admit and r.evidence["lane_skip"]["why"] == "cand_variant"


def test_keep_rare_skips_group_members():
    # 㫖 属字组 zhi，由字组按刻形判，不走这条
    n, r = _keep_rare("㫖", [("㫖", 0.99), ("旨", 0.97)])
    assert n == 0 and r.evidence["lane_skip"]["why"] == "cand_variant"


def test_keep_rare_off_restores_guard():
    n, r = _keep_rare("䘮", [("䘮", 0.989), ("喪", 0.955)], lane_variant_keep_rare=False)
    assert n == 0 and r.evidence["lane_skip"]["why"] == "cand_variant"

pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest


@pytest.mark.parametrize("doubt", ["group_flow_disagree", "group_flow_ctx_contra"])
def test_r4_never_lifts_group_flow_contra(doubt):
    """字组流程里文意给了别的字而留审的格（vol11 18:5:11 顧炎武日知錄被 witness3 按整理本放成曰）：
    补放通道不按整理本字放回，`lane_keep_ref_review` 关了也不放。"""
    chars = BODY[:30]
    for keep in (True, False):
        out = _page(chars, {5: dict(doubts=[doubt], char="夫")})
        wits = [_wit(f"{k}.txt", "前" + chars[:4] + "天" + chars[5:] + "後") for k in "dwy"]
        n, rs = _run(out, lib={5: "天"}, coord=_ids({5: "天"}), wits=wits, lane_coord=True, lane_keep_ref_review=keep)
        assert n == 0 and not rs[5].admit


# ── 异体形近规则先于印章（occluded_variant_first，A31 10-28）──────────────────

def _seal_variant(cands, **params):
    """第 5 格遮挡、默认字＝坐标对位字「旨」；库候选 `cands`。"""
    chars = BODY[:20]
    out = _page(chars, {5: dict(doubts=["occluded"], char="旨",
                                evidence={"occluded": {"density": 9.0, "via": "coord"}})})
    p = SeedAdmitParams(db_path="x", lane_seal=True, **params)
    mm = {f"{B}:1:5": NS(char=None, candidates=cands, guard=None)}
    n = _review_lanes_pass(p, out, mm, {}, _ids({5: "旨"}), _vm(), None)
    return n, out[0].chars[4]


def test_seal_variant_first_admits_when_lib_top_is_default():
    """库首位＝默认字、候选里有它的异体：异体护栏不拦，R5 放默认字。"""
    n, r = _seal_variant([("旨", 0.97), ("㫖", 0.96)])
    assert n == 1 and r.admit and r.char == "旨" and r.channel == "seal"
    assert r.evidence["lane"]["variant_first"] == "㫖"


def test_seal_variant_first_off_keeps_old_guard():
    n, r = _seal_variant([("旨", 0.97), ("㫖", 0.96)], occluded_variant_first=False)
    assert n == 0 and not r.admit and r.evidence["lane_skip"]["why"] == "cand_variant"


def test_seal_variant_first_needs_lib_top_equal_and_cov():
    n, r = _seal_variant([("㫖", 0.97), ("旨", 0.96)])        # 库首位是异体：形说不准，照旧送审
    assert n == 0 and r.evidence["lane_skip"]["why"] == "cand_variant"
    n, r = _seal_variant([("旨", 0.85), ("㫖", 0.84)])        # 覆盖度 < seal_lib_cov
    assert n == 0 and r.evidence["lane_skip"]["why"] == "cand_variant"


def test_occluded_variant_first_default_not_in_dump():
    assert "occluded_variant_first" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", occluded_variant_first=False).model_dump()["occluded_variant_first"] is False


def test_follow_ref_decide_allows_occluded_only_when_variant_first():
    from open_guji_cv.steps.seed_admit import follow_ref_decide
    kw = dict(admit=False, channel=None, char="盖", doubts=["occluded"], ref="盖", cands=[("蓋", 0.97), ("善", 0.5)],
              verdict=None, guard=None, ctx_char=None, rules={"盖": "蓋"}, cov_min=0.92, gap_min=0.005)
    assert follow_ref_decide(**kw) is None
    assert follow_ref_decide(**kw, allow_occluded=True) == "admit"


def _flow_occluded(monkeypatch, lifted_char, **params):
    """字组流程在遮挡格上放行 `lifted_char` 时，`_group_flow_pass` 的核对（`occluded_variant_first` ③）。"""
    from types import SimpleNamespace as _NS
    import open_guji_cv.groups.flow as flow
    from open_guji_cv.steps.seed_admit import _group_flow_pass
    out = _page(BODY[:10], {3: dict(doubts=["occluded"], char="黃", evidence={"occluded": {"density": 9.0, "via": "coord"}})})

    def fake(seq, amap, cands_of, blocked, cfg, **kw):
        rec = next(r for r in seq if r.slot == 3)
        assert not blocked(rec) if params.get("occluded_variant_first", True) else blocked(rec)
        rec.admit, rec.channel, rec.provenance, rec.char, rec.doubts = True, "group_flow", "context", lifted_char, []
        return _NS(lifted=1, demoted=0)
    monkeypatch.setattr(flow, "group_flow_pass", fake)
    p = SeedAdmitParams(db_path="x", **params)
    net = _group_flow_pass(p, out, {}, {}, None, 1, {})
    return net, out[0].chars[2]


def test_group_flow_occluded_admits_only_when_char_is_default(monkeypatch):
    net, r = _flow_occluded(monkeypatch, "黃")
    assert net == 1 and r.admit and r.char == "黃" and r.evidence["occluded_variant_first"] == "group_flow"
    net, r = _flow_occluded(monkeypatch, "黄")            # 给了别的字：退回待审，字和疑问原样
    assert net == 0 and not r.admit and r.char == "黃" and r.doubts == ["occluded"] and r.channel is None


def test_group_flow_occluded_still_blocked_when_off(monkeypatch):
    net, r = _flow_occluded(monkeypatch, "黃", occluded_variant_first=False)
    assert r.admit      # 关着时 blocked() 为真（fake 里断言过），这里的放行是 fake 硬放的，不退回
