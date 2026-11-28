"""4 定字出口 gate decide_gate（2026-11-28，CV4）：只检测、不判断；不改任何格、不影响别的步骤的指纹。"""
from __future__ import annotations

import copy

import open_guji_cv.steps  # noqa: F401  —— 注册 Step 与闸
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.step import STEPS
from open_guji_cv.gates.decide_gate import DecideGateParams, detect_page
from open_guji_cv.products.kinds.decide_gate import PageDecideGate
from open_guji_cv.products.kinds.recog import (AdmitRec, AlignRec, ColumnAdmit, CoordRec, MatchRec, ColumnMatch,
                                               PageAdmit, PageAlignRef, PageMatch)

PAGE = 7
TEXT = "天地玄黃宇宙洪荒日月盈昃"


def _rec(i: int, ch: str, *, admit=True, channel="match_ref", evidence=None, provenance="match") -> AdmitRec:
    return AdmitRec(id=f"v:{PAGE}:1:{i}", slot=i, admit=admit, channel=channel, char=ch, provenance=provenance,
                    evidence=evidence if evidence is not None else {})


def _page(chars: list[AdmitRec], **kw) -> PageAdmit:
    return PageAdmit(page=PAGE, n_auto=sum(1 for c in chars if c.admit),
                     columns=[ColumnAdmit(col=1, chars=chars)], **kw)


def _align(text: str = TEXT, **kw) -> PageAlignRef:
    return PageAlignRef(page=PAGE, anchored=True,
                        coord=[CoordRec(id=f"v:{PAGE}:1:{i + 1}", col=1, slot=i + 1, ref_char=c) for i, c in enumerate(text)],
                        chars=[AlignRec(id=f"v:{PAGE}:1:{i + 1}", col=1, slot=i + 1, align_char=c, align_op="equal")
                               for i, c in enumerate(text)], **kw)


def _match(text: str = TEXT) -> PageMatch:
    return PageMatch(page=PAGE, columns=[ColumnMatch(col=1, chars=[
        MatchRec(id=f"v:{PAGE}:1:{i + 1}", slot=i + 1, verdict="same", char=c, candidates=[(c, 0.99)])
        for i, c in enumerate(text)])])


def _names(res: PageDecideGate, level=None):
    return sorted({c.name for c in res.checks if level in (None, c.level)})


def test_clean_page_passes():
    recs = [_rec(i + 1, c) for i, c in enumerate(TEXT)]
    res = detect_page(PAGE, _page(recs), align=_align(), match=_match())
    assert res.passed and res.checks == []
    assert res.metrics["n_admit"] == len(TEXT) and res.metrics["admit_rate"] == 1.0


def test_ref_shift_fails_on_consecutive_shifted_chars():
    # 放行字恰是参校本后一位的字（对位错开一位）：连续 4 格
    recs = [_rec(i + 1, TEXT[i + 1] if 2 <= i + 1 <= 5 else TEXT[i]) for i in range(len(TEXT) - 1)]
    res = detect_page(PAGE, _page(recs), align=_align(), match=_match(), params=DecideGateParams(check_group=False))
    shifts = [c for c in res.checks if c.name == "ref_shift"]
    assert len(shifts) == 1 and shifts[0].level == "fail" and shifts[0].unit == "col"
    assert shifts[0].metrics["shift"] == 1 and shifts[0].metrics["run"] == 4
    assert not res.passed


def test_ref_shift_needs_min_run_and_skips_human():
    recs = [_rec(i + 1, TEXT[i + 1] if 2 <= i + 1 <= 3 else TEXT[i]) for i in range(len(TEXT) - 1)]     # 只错 2 格 < k=3
    res = detect_page(PAGE, _page(recs), align=_align(), match=_match())
    assert "ref_shift" not in _names(res)
    hum = [_rec(i + 1, TEXT[i + 1] if 2 <= i + 1 <= 5 else TEXT[i], channel="human", provenance="human",
                evidence={"human": True}) for i in range(len(TEXT) - 1)]
    assert "ref_shift" not in _names(detect_page(PAGE, _page(hum), align=_align(), match=_match()))


def test_char_not_in_evidence():
    recs = [_rec(1, TEXT[0]), _rec(2, "龘")]           # 第 2 格放的字不在候选、参校本、证据里
    res = detect_page(PAGE, _page(recs), align=_align(), match=_match())
    bad = [c for c in res.checks if c.name == "char_not_in_evidence"]
    assert [c.key for c in bad] == [f"v:{PAGE}:1:2"] and bad[0].level == "fail"
    # 证据里（如字组留痕）出现过就算有出处；人裁不查
    ok = [_rec(1, TEXT[0]), _rec(2, "龘", evidence={"form": {"forms": ["龘"]}})]
    assert "char_not_in_evidence" not in _names(detect_page(PAGE, _page(ok), align=_align(), match=_match()))
    hum = [_rec(1, TEXT[0]), _rec(2, "龘", channel="human", provenance="human", evidence={"human": True})]
    assert "char_not_in_evidence" not in _names(detect_page(PAGE, _page(hum), align=_align(), match=_match()))


def test_rare_codepoint_flag():
    # 参校本作常用的「變」，放行了罕用码位「𬽠」（變／𬽠 在边表里是异体）
    al = PageAlignRef(page=PAGE, anchored=True, coord=[CoordRec(id=f"v:{PAGE}:1:1", col=1, slot=1, ref_char="變")])
    mt = PageMatch(page=PAGE, columns=[ColumnMatch(col=1, chars=[MatchRec(id=f"v:{PAGE}:1:1", slot=1, verdict="same",
                                                                           char="𬽠", candidates=[("𬽠", 0.99)])])])
    res = detect_page(PAGE, _page([_rec(1, "𬽠")]), align=al, match=mt)
    fl = [c for c in res.checks if c.name == "rare_codepoint"]
    assert len(fl) == 1 and fl[0].level == "flag" and fl[0].metrics["ref"] == "變" and res.passed
    # 放行字等于参校本字，或参校本字也不常用：不标
    al2 = PageAlignRef(page=PAGE, anchored=True, coord=[CoordRec(id=f"v:{PAGE}:1:1", col=1, slot=1, ref_char="𬽠")])
    assert "rare_codepoint" not in _names(detect_page(PAGE, _page([_rec(1, "𬽠")]), align=al2, match=mt))


def test_review_cells_are_not_checked():
    recs = [_rec(1, TEXT[0]), _rec(2, "龘", admit=False, channel=None)]
    assert detect_page(PAGE, _page(recs), align=_align(), match=_match()).checks == []


def test_page_and_col_flags():
    recs = [_rec(i + 1, c) for i, c in enumerate(TEXT)]
    # 参校本缺席
    res = detect_page(PAGE, _page(recs), match=_match())
    assert "no_align_ref" in _names(res, "flag") and res.passed and res.metrics["missing"][0] == "align_ref"
    # 没锚上也没坐标对位，却靠参校本通道放行
    un = PageAlignRef(page=PAGE, anchored=False)
    assert "unanchored_ref_admit" in _names(detect_page(PAGE, _page(recs), align=un, match=_match()), "flag")
    # 坐标退回、备选切法
    al = _align(coord_fallback={"1": "列内字数对不上"})
    res = detect_page(PAGE, _page(recs, alt_cols=[1]), align=al, match=_match())
    assert {"col_coord_fallback", "col_alt_cut"} <= set(_names(res, "flag"))


def test_step_error_and_human_unbound_and_group():
    recs = [_rec(1, TEXT[0], evidence={"human_unbound": {"char": "地", "event": "e1", "status": "review"}}),
            _rec(2, TEXT[1])]
    pg = _page(recs)
    pg.columns.append(ColumnAdmit(col=2, ok=False, error="boom"))
    res = detect_page(PAGE, pg, align=_align(), match=_match(), group_chars="地", params=DecideGateParams(check_group=True))
    assert ("step_error", "fail") in {(c.name, c.level) for c in res.checks}
    flags = {c.name: c for c in res.checks if c.level == "flag"}
    assert flags["human_conflict"].metrics["human"] == "地"          # 绑丢的人裁字与放行字（天）不同
    assert flags["group_without_4d"].key == f"v:{PAGE}:1:2"          # 放行字「地」在字组里却没有字组证据
    assert not res.passed
    # 切字阶段就没过的列：不重复报 fail，只记 flag col_not_cut
    pg2 = _page([_rec(1, TEXT[0])])
    pg2.columns.append(ColumnAdmit(col=2, ok=False, error="未过交接闸: 页级未过 L1"))
    r2 = detect_page(PAGE, pg2, align=_align(), match=_match())
    assert r2.passed and "col_not_cut" in _names(r2, "flag") and "step_error" not in _names(r2)
    # 默认不做字组漏判
    assert "group_without_4d" not in _names(detect_page(PAGE, pg, align=_align(), match=_match(), group_chars="地"))


def test_detect_does_not_mutate_inputs():
    recs = [_rec(i + 1, TEXT[i + 1] if 2 <= i + 1 <= 5 else TEXT[i]) for i in range(len(TEXT) - 1)]
    pg, al, mt = _page(recs), _align(), _match()
    before = [copy.deepcopy(x.model_dump()) for x in (pg, al, mt)]
    detect_page(PAGE, pg, align=al, match=mt, group_chars=TEXT, params=DecideGateParams(check_group=True))
    assert [x.model_dump() for x in (pg, al, mt)] == before


def test_gate_attached_to_seed_admit_and_isolated():
    keben = load_pipeline("keben_body_v2")
    assert keben.gate_of("seed_admit").id == "decide_gate"
    assert keben.producer_of("decide_gate").spec.id == "decide_gate"
    spec = STEPS["decide_gate"].spec
    assert spec.produces == ("decide_gate",) and "seed_admit" in spec.consumes
    # 只检测：没有任何别的 Step 读它，也没有别的 Step 把它的模块列进 code_deps
    for sid, st in STEPS.items():
        if sid == "decide_gate":
            continue
        assert "decide_gate" not in st.spec.consumes + st.spec.optional_consumes, sid
        assert not any(m.endswith("decide_gate") for m in st.spec.code_deps), sid
