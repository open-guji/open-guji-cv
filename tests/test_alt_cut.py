"""row_segment `alt_cut`（第 7 轮，史记）：备选切法的产物字段、字块键、下游视图。

- 没有备选列时，四种产物不落 `alt_columns`／`alt_cols` 字段（产物逐字节与开关加之前相同）；
- `with_alt` 只换点名的列；
- 备选字块键与主切法不撞，`split_alt_key` 拆得回去；
- cell_shrink 给备选列出带 `alt` 的键，缓存清掉后按备选格网再生得出来；
- `products.alt_view`：只有 align_ref 挑中的列才换键、换视图，5b/6 丢掉这些列。
"""

from __future__ import annotations

import json

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类与步骤
from helpers import make_book, run_keben_chain


def _cells_with_alt(cells):
    """主切法格网拷一份当第一个有格的列的备选格网（格框整体下移 3px，字块会不同）。"""
    from open_guji_cv.products.kinds.cells import CellRec
    c1 = next(c for c in cells.columns if c.ok and len(c.cells) > 3)
    moved = c1.model_copy(update={"cells": [
        CellRec(**{**b.model_dump(), "y0": b.y0 + 3, "y1": b.y1 + 3}) for b in c1.cells]})
    return cells.model_copy(update={"alt_columns": [moved]})


def test_empty_alt_fields_not_serialized():
    from open_guji_cv.products.kinds.cells import PageCells
    from open_guji_cv.products.kinds.chars import PageChars
    from open_guji_cv.products.kinds.recog import PageAlignRef, PageMatch
    for obj in (PageCells(page=1, period=None, ref_w=None, columns=[]), PageChars(page=1, columns=[]),
                PageMatch(page=1, db_fingerprint="x"), PageAlignRef(page=1)):
        d = obj.model_dump()
        assert "alt_columns" not in d and "alt_cols" not in d, type(obj).__name__
        assert "alt_" not in obj.model_dump_json()


def test_alt_key_roundtrip():
    from open_guji_cv.core.spec import alt_cell_key, cell_key, split_alt_key
    k = alt_cell_key(12, 3, 5)
    assert k == cell_key(12, 3, 5) + "alt"
    assert split_alt_key(k + "a") == (cell_key(12, 3, 5), True, "a")
    assert split_alt_key(k) == (cell_key(12, 3, 5), True, "")
    assert split_alt_key(cell_key(12, 3, 5) + "b") == (cell_key(12, 3, 5), False, "b")
    assert split_alt_key(alt_cell_key(1, 4, -1) + "b") == ("p0001c04s-1", True, "b")


def test_alt_patch_key_only_chosen_cols():
    from open_guji_cv.products.alt_view import alt_patch_key
    assert alt_patch_key("p0099c04s12a", {4}) == "p0099c04s12alta"
    assert alt_patch_key("p0099c04s-1b", {4}) == "p0099c04s-1altb"
    assert alt_patch_key("p0099c05s12a", {4}) == "p0099c05s12a"
    assert alt_patch_key("p0099c04s12", frozenset()) == "p0099c04s12"


def test_cell_shrink_alt_columns_keys_and_render(tmp_path, monkeypatch):
    book = make_book(expected_cols=4, chars_per_line=21)
    ctx, out = run_keben_chain(tmp_path, monkeypatch, book=book, through="row_segment_gate", h=2000,
                               n_cols=4, w=500, period=100, col_n_chars={4: 3, 3: 7, 2: 12, 1: 5})
    cells = _cells_with_alt(out["cells"])
    ctx.store.write(book.id, "row_segment", "p0001", {"cells": cells})
    from open_guji_cv.core.step import STEPS
    res = STEPS["cell_shrink"].run_page(ctx, 1)
    chars = res["char_index"]
    assert [c.col for c in chars.alt_columns] == [cells.alt_columns[0].col]
    alt_keys = [r.patch_key for r in chars.alt_columns[0].chars if r.patch_key]
    main_keys = {r.patch_key for c in chars.columns for r in c.chars if r.patch_key}
    assert alt_keys and all("alt" in k for k in alt_keys)
    assert not set(alt_keys) & main_keys
    ctx.store.write(book.id, "cell_shrink", "p0001", res)
    # 缓存删掉后，备选键按备选格网再生得出来，图与主切法同号格不同
    k = alt_keys[0]
    img = STEPS["cell_shrink"].render(ctx, "char_patch", k)
    assert img is not None
    from open_guji_cv.core.spec import split_alt_key
    main_k = split_alt_key(k)[0] + split_alt_key(k)[2]
    main_img = STEPS["cell_shrink"].render(ctx, "char_patch", main_k)
    a, b = np.asarray(img), np.asarray(main_img)
    assert a.shape != b.shape or not np.array_equal(a, b)
    # 落盘的产物里有 alt_columns；去掉它就是主切法那份
    raw = json.loads(ctx.store.path(book.id, "cell_shrink", "p0001").read_text(encoding="utf-8"))
    assert raw["char_index"].get("alt_columns")


def test_alt_view_product_and_image(tmp_path):
    from open_guji_cv.products.alt_view import AltView
    from open_guji_cv.products.kinds.recog import (ColumnDecision, ColumnMatch, MatchRec,
                                                   PageAlignRef, PageDecision, PageMatch)

    def col(c, ch):
        return ColumnMatch(col=c, ok=True, chars=[MatchRec(id=f"b:1:{c}:1", slot=1, verdict="same", char=ch)])

    match = PageMatch(page=1, db_fingerprint="x", columns=[col(1, "甲"), col(2, "乙")],
                      alt_columns=[col(2, "丙")])
    dec = PageDecision(page=1, strategy="t", columns=[ColumnDecision(col=1, ok=True), ColumnDecision(col=2, ok=True)])
    prods = {"glyph_match": match, "context_decision": dec, "align_ref": PageAlignRef(page=1, alt_cols=[2])}
    seen = []

    class Ctx:
        def product(self, kind, page):
            return prods[kind]

        def image(self, kind, key):
            seen.append(key)
            return key

    av = AltView(Ctx())
    m = av.product("glyph_match", 1)
    assert [c.chars[0].char for c in m.columns] == ["甲", "丙"] and not m.alt_columns
    assert [c.col for c in av.product("context_decision", 1).columns] == [1]
    assert av.image("char_patch", "p0001c02s1") == "p0001c02s1alt"
    assert av.image("char_patch", "p0001c01s1") == "p0001c01s1"
    # 没挑中：原样
    prods["align_ref"] = PageAlignRef(page=1)
    av2 = AltView(Ctx())
    assert [c.chars[0].char for c in av2.product("glyph_match", 1).columns] == ["甲", "乙"]


def test_resolve_patch_key_reads_align_ref(tmp_path):
    from open_guji_cv.products.alt_view import read_view, resolve_patch_key
    from open_guji_cv.products.kinds.recog import PageAlignRef
    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")
    assert resolve_patch_key("b", "p0003c02s4a", st) == "p0003c02s4a"
    st.write("b", "align_ref", "p0003", {"align_ref": PageAlignRef(page=3, alt_cols=[2])})
    assert resolve_patch_key("b", "p0003c02s4a", st) == "p0003c02s4alta"
    assert resolve_patch_key("b", "p0003c01s4a", st) == "p0003c01s4a"
    assert read_view(st, "b", "align_ref", "p0003", "align_ref").alt_cols == [2]


def test_shifted_counts_neighbour_slot_matches():
    """备选格网错一格：机器字整段等于参校本邻格字 → `_shifted` 数得出来；对齐的列数 0。"""
    from open_guji_cv.products.kinds.recog import CoordRec, PageAlignRef
    from open_guji_cv.steps.align_ref import _shifted
    ref = "邑括地志云杜陵"
    recs = [CoordRec(id=f"b:1:8:{i + 1}a", col=8, slot=i + 1, sub="a", ref_char=ch) for i, ch in enumerate(ref)]
    res = PageAlignRef(page=1, coord=recs)
    ok = {f"b:1:8:{i + 1}a": ch for i, ch in enumerate(ref)}
    shifted = {f"b:1:8:{i + 2}a": ch for i, ch in enumerate(ref[:-1])}   # 机器第 n 格＝参校本第 n−1 格
    assert _shifted(res, ok.get, 8) == 0
    assert _shifted(res, shifted.get, 8) == len(ref) - 1


def test_admit_mode_pick_and_merge():
    """alt_select="admit"：两遍准入逐列比，只换待审少 ≥2、背书不少、冲突不多的列；页计数按列差补。"""
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, CoordRec, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import _merge_admit, _pick_alt_cols

    def col(c, n_ok, n_rev, ch="甲"):
        recs = [AdmitRec(id=f"b:1:{c}:{i + 1}", slot=i + 1, admit=True, channel="match_ref", char=ch) for i in range(n_ok)]
        recs += [AdmitRec(id=f"b:1:{c}:{n_ok + i + 1}", slot=n_ok + i + 1) for i in range(n_rev)]
        return ColumnAdmit(col=c, chars=recs)
    main = PageAdmit(page=1, n_auto=8, n_review=12, columns=[col(1, 4, 6), col(2, 4, 6)])
    alt = PageAdmit(page=1, n_auto=13, n_review=7, columns=[col(1, 9, 1), col(2, 5, 5)])
    ref = PageAlignRef(page=1, coord=[CoordRec(id="b:1:1:1", col=1, slot=1, ref_char="甲")])
    chosen = _pick_alt_cols([1, 2], main, alt, ref, ref, None, None)
    assert chosen == [1]                          # 第 2 列只少 1 格，不换
    m = _merge_admit(main, alt, chosen)
    assert (m.n_auto, m.n_review, m.alt_cols) == (13, 7, [1])
    assert m.column(1).chars[8].admit and len(m.column(2).chars) == 10
    assert "alt_cols" not in PageAdmit(page=1).model_dump()
    # 备选那遍冲突多了（放行字≠坐标字）：不换
    alt_bad = PageAdmit(page=1, columns=[col(1, 9, 1, ch="乙"), col(2, 5, 5)])
    assert _pick_alt_cols([1], main, alt_bad, ref, ref, None, None) == []
    # 备选那遍放行全靠整理本（witnesses_coord），背书格变少：不换（用户 11-04 定 B）
    weak = col(1, 9, 1)
    for r in weak.chars[:9]:
        r.channel = "witnesses_coord"
    assert _pick_alt_cols([1], main, PageAdmit(page=1, columns=[weak, col(2, 5, 5)]), ref, ref, None, None) == []
    # alt_backed_gain：待审只少 1 格、背书多 ≥1 也换（缺省 0 不换；脉经 01 10:2）
    assert _pick_alt_cols([2], main, alt, ref, ref, None, None, backed_gain=1) == [2]
    assert _pick_alt_cols([2], main, alt, ref, ref, None, None, backed_gain=2) == []
    assert _pick_alt_cols([2], main, PageAdmit(page=1, columns=[col(2, 4, 5)]), ref, ref, None, None, backed_gain=1) == []


def test_admit_mode_p_ref_is_ordinary_admit_in_stats():
    """`_col_stats` 不再把 p_ref 格按待审算（1.79：开 p_ref 时选列改用不跑 p_ref 的两遍，见 `_NO_P_REF`）。"""
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import _NO_P_REF, _col_stats
    recs = [AdmitRec(id="b:1:1:1", slot=1, admit=True, channel="p_ref", char="乙"), AdmitRec(id="b:1:1:2", slot=2)]
    assert _col_stats(PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=recs)]), 1, PageAlignRef(page=1)) == (1, 0, 0)
    assert _NO_P_REF.get() is False


def test_admit_mode_first_cell_guard():
    """备选首个正文整字格墨高超过其余中位数 1.6 倍：不换（只拦）。"""
    from types import SimpleNamespace as NS
    from open_guji_cv.steps.seed_admit import _first_cell_tall

    def chars(h0):
        hs = [h0] + [40] * 6
        rs = [NS(sub=None, slot=i + 1, patch_key=f"k{i}", bbox_page=[0, 0, 30, h]) for i, h in enumerate(hs)]
        return NS(columns=[NS(col=1, chars=rs)])
    assert _first_cell_tall(chars(70), 1) and not _first_cell_tall(chars(60), 1)
    assert not _first_cell_tall(chars(70), 2) and not _first_cell_tall(None, 1)


def test_admit_mode_views_and_offline_cols(tmp_path):
    from open_guji_cv.products.alt_view import alt_cols_of, alt_override, with_alt_ref
    from open_guji_cv.products.kinds.recog import AltDraft, CoordRec, PageAdmit, PageAlignRef
    from open_guji_cv.products.store import ProductStore
    ref = PageAlignRef(page=3, coord=[CoordRec(id="b:3:2:1", col=2, slot=1, ref_char="甲")], alt_cand=[2],
                       alt_draft=AltDraft(coord=[CoordRec(id="b:3:2:1", col=2, slot=1, ref_char="乙")], coord_cols=[2]))
    v = with_alt_ref(ref, {2})
    assert [r.ref_char for r in v.coord] == ["乙"] and v.alt_cols == [2] and ref.alt_cols == []
    assert with_alt_ref(ref, set()) is ref
    st = ProductStore(tmp_path / "products")
    st.write("b", "align_ref", "p0003", {"align_ref": ref})
    assert alt_cols_of("b", 3, st) == frozenset()          # 候选不算换列
    st.write("b", "seed_admit", "p0003", {"seed_admit": PageAdmit(page=3, alt_cols=[2])})
    assert alt_cols_of("b", 3, st) == frozenset({2})       # 先读 seed_admit
    with alt_override("b", 3, ()):
        assert alt_cols_of("b", 3, st) == frozenset()      # 准入时钉住的列优先


def test_admit_mode_require_matched():
    """alt_require_matched：备选格网多出没有坐标字的格（02:106:7 的多切大字格）→ 不换；关时照旧换；备选没坐标字的格更少 → 照换。"""
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, CoordRec, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import _pick_alt_cols

    def col(n_ok, n_rev):
        recs = [AdmitRec(id=f"b:1:7:{i + 1}", slot=i + 1, admit=True, channel="match_ref", char="甲") for i in range(n_ok)]
        recs += [AdmitRec(id=f"b:1:7:{n_ok + i + 1}", slot=n_ok + i + 1) for i in range(n_rev)]
        return ColumnAdmit(col=7, chars=recs)

    def coord(n):
        return PageAlignRef(page=1, coord=[CoordRec(id=f"b:1:7:{i + 1}", col=7, slot=i + 1, ref_char="甲") for i in range(n)])
    main = PageAdmit(page=1, columns=[col(8, 3)])      # 11 格全有坐标字
    alt = PageAdmit(page=1, columns=[col(8, 1)])       # 9 格，坐标字只给 8 格 → 多 1 格没有
    assert _pick_alt_cols([7], main, alt, coord(11), coord(8), None, None) == [7]
    assert _pick_alt_cols([7], main, alt, coord(11), coord(8), None, None, require_matched=True) == []
    # 主切法反而有 4 格没坐标字、备选更少：照换
    assert _pick_alt_cols([7], main, alt, coord(7), coord(8), None, None, require_matched=True) == [7]



def test_alt_same_ink_cells_ignores_blank_and_slot():
    """备选只差空格框和格号（史記 r43 09:194:5：闸判抬头一格，格号 -1..14 对主切法 1..15）→ 不出备选。"""
    from open_guji_cv.products.kinds.cells import CellRec
    from open_guji_cv.steps.row_segment import _alt_same_ink_cells

    def cell(slot, y0, kind="char"):
        return CellRec(slot=slot, pos=slot, y0=y0, y1=y0 + 90, x0=0, x1=80, kind=kind, sub="", order=slot,
                       ink_ratio=0.1)
    main = [cell(i, 100 * i) for i in range(1, 15)] + [cell(15, 1500, "blank")]
    shifted = [cell(i - 2, 100 * i) for i in range(1, 15)] + [cell(13, 1500, "blank"), cell(14, 1560, "blank")]
    assert _alt_same_ink_cells(main, shifted)
    moved = [cell(i, 100 * i + (5 if i == 7 else 0)) for i in range(1, 15)] + [cell(15, 1500, "blank")]
    assert not _alt_same_ink_cells(main, moved)
    became_blank = [cell(i, 100 * i, "blank" if i == 14 else "char") for i in range(1, 16)]
    assert not _alt_same_ink_cells(main, became_blank)


def test_alt_cut_rev_only_in_dump_when_on():
    from open_guji_cv.steps.row_segment import ALT_CUT_REV, RowSegmentParams
    assert "alt_cut_rev" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(alt_cut=True).model_dump()["alt_cut_rev"] == ALT_CUT_REV


# ── 不分行参照（text）页按列挑备选、alt_nojz（2026-11-19 脉经，GUJI-774）──────────────────────

def test_text_mode_pick_by_equal_count_and_admit_rate():
    """ref_kind="text"：没有坐标字。备选那份 equal 多 ≥2、待审不多就换（半字也放行，只比待审挑不出）；
    放行率比主切法低 5 个点以上不换（整列真小注换成大字格，格少待审也少）。"""
    from open_guji_cv.products.kinds.recog import AdmitRec, AlignRec, ColumnAdmit, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import _pick_alt_cols

    def col(n_ok, n_rev):
        recs = [AdmitRec(id=f"b:1:3:{i + 1}", slot=i + 1, admit=True, channel="match_ref", char="甲") for i in range(n_ok)]
        recs += [AdmitRec(id=f"b:1:3:{n_ok + i + 1}", slot=n_ok + i + 1) for i in range(n_rev)]
        return ColumnAdmit(col=3, chars=recs)

    def ref(n_eq):
        return PageAlignRef(page=1, ref_kind="text", chars=[
            AlignRec(id=f"b:1:3:{i + 1}", col=3, slot=i + 1, align_char="甲", align_op="equal") for i in range(n_eq)])
    main = PageAdmit(page=1, columns=[col(19, 3)])     # 大字劈成半字照样放行：待审 3
    alt = PageAdmit(page=1, columns=[col(18, 2)])      # 待审只少 1，按待审不换
    assert _pick_alt_cols([3], main, alt, PageAlignRef(page=1), PageAlignRef(page=1), None, None) == []
    assert _pick_alt_cols([3], main, alt, ref(11), ref(15), None, None) == [3]
    assert _pick_alt_cols([3], main, alt, ref(14), ref(15), None, None) == []        # equal 只多 1
    # 放行率掉了（13/40 → 0/20）：哪条路都不换
    main2, alt2 = PageAdmit(page=1, columns=[col(13, 27)]), PageAdmit(page=1, columns=[col(0, 20)])
    assert _pick_alt_cols([3], main2, alt2, ref(5), ref(9), None, None) == []


def test_alt_text_ok_and_merge_alt_text_chars():
    from types import SimpleNamespace as NS
    from open_guji_cv.products.alt_view import with_alt_ref
    from open_guji_cv.products.kinds.recog import AlignRec, AltDraft, PageAlignRef
    from open_guji_cv.steps.align_ref import _alt_text_ok
    hi, lo = NS(cov=0.99, cand_variants=[]), NS(cov=0.5, cand_variants=[])
    assert _alt_text_ok([hi] * 20 + [lo] * 2, [hi] * 18 + [lo] * 2)       # 0.909 → 0.90：差不到 5 个点
    assert not _alt_text_ok([hi] * 20, [hi] * 10 + [lo] * 10)
    assert not _alt_text_ok([], [hi])
    rec = lambda c, s, ch: AlignRec(id=f"b:1:{c}:{s}", col=c, slot=s, align_char=ch, align_op="equal")  # noqa: E731
    ref = PageAlignRef(page=1, ref_kind="text", chars=[rec(1, 1, "甲"), rec(2, 1, "乙")], alt_cand=[2],
                       alt_draft=AltDraft(chars=[rec(2, 1, "丙"), rec(2, 2, "丁")]))
    v = with_alt_ref(ref, {2})
    assert [(r.col, r.align_char) for r in v.chars] == [(1, "甲"), (2, "丙"), (2, "丁")]
    assert "chars" not in AltDraft().model_dump()                            # 坐标页草稿不落 chars


def test_alt_nojz_param_off_by_default_not_in_dump():
    from open_guji_cv.steps.row_segment import RowSegmentParams
    assert "alt_nojz" not in RowSegmentParams(cut_judge="rule").model_dump()
    assert RowSegmentParams(cut_judge="rule", alt_nojz=True).model_dump()["alt_nojz"] is True


# ── 备选格线表 alt_cuts、备选列的上下文裁决（2026-11-20 脉经，GUJI-774）──────────────────────
def test_alt_cuts_param_off_by_default_and_fingerprint(tmp_path):
    from open_guji_cv.steps.row_segment import RowSegmentParams
    d = RowSegmentParams(cut_judge="rule").model_dump()
    assert "alt_cuts" not in d and "alt_cuts_fingerprint" not in d
    t = tmp_path / "cuts.jsonl"
    t.write_text('{"vol": "01", "page": 7, "col": 7, "cuts": [0, 10, 20], "col_h": 20}\n', encoding="utf-8")
    on = RowSegmentParams(cut_judge="rule", alt_cuts=str(t)).model_dump()
    assert on["alt_cuts"] == str(t) and len(on["alt_cuts_fingerprint"]) == 16
    import pytest
    with pytest.raises(ValueError):
        RowSegmentParams(cut_judge="rule", alt_cuts=str(tmp_path / "missing.jsonl"))


def test_context_decision_alt_columns_view():
    from open_guji_cv.products.alt_view import view
    from open_guji_cv.products.kinds.recog import ColumnDecision, DecisionRec, PageDecision
    from open_guji_cv.steps.context_decide import ContextDecideParams

    def col(c, ch):
        return ColumnDecision(col=c, ok=True, chars=[DecisionRec(id=f"b:1:{c}:1", slot=1, char=ch, source="context")])
    old = PageDecision(page=1, columns=[col(1, "甲"), col(2, "乙")])
    assert "alt_columns" not in old.model_dump()
    assert [c.col for c in view(old, "context_decision", {2}).columns] == [1]          # 没有备选裁决：照旧丢
    new = PageDecision(page=1, columns=[col(1, "甲"), col(2, "乙")], alt_columns=[col(2, "丙"), col(1, "丁")])
    v = view(new, "context_decision", {2})
    assert [(c.col, c.chars[0].char) for c in v.columns] == [(1, "甲"), (2, "丙")]      # 只换点名的列
    assert view(new, "context_decision", set()) is new
    assert "alt_columns" not in ContextDecideParams().model_dump()
    assert ContextDecideParams(alt_columns=True).model_dump()["alt_columns"] is True


def test_yolo_alt_cuts_clean_and_cuts():
    import importlib.util
    from pathlib import Path
    from open_guji_cv.impl.keben.yolo_tool_infer import Box
    spec = importlib.util.spec_from_file_location("yac", Path(__file__).parents[1] / "scripts" / "yolo_alt_cuts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    bx = lambda y0, y1, conf=0.9: Box(10, y0, 90, y1, conf, "ch")
    raw = [bx(100 * i + 5, 100 * i + 95) for i in range(5)]
    raw += [bx(205, 240), bx(500, 545), bx(548, 590)]     # 「書」下半另框、一个高字劈成上下两框
    raw += [bx(990, 1000)]                                 # 版框线碎点
    got = m.clean(raw)
    assert len(got) == 6 and got[-1][1] == 500 and got[-1][3] == 590
    cuts = m.column_cuts(got, 8, 900)
    assert len(cuts) == 9 and cuts[0] == 0.0 and cuts[-1] == 900.0
    assert cuts[1] == 100.0                                # 两框之间
    assert m.column_cuts(got, 5, 900) is None              # 框多于格数
    lead = m.column_cuts([[10, 300, 90, 390], [10, 400, 90, 490]], 6, 900)   # 低三格起头
    top = 300 - 0.1 * 90 * 1.05                            # 首字上缘让 0.1 个字高
    assert lead[:4] == [0.0, round(top / 3, 1), round(2 * top / 3, 1), round(top, 1)]


# ── 整列写定的备选格 alt_cells（2026-11-20 脉经 01，GUJI-774）──────────────────────────────
def test_alt_cells_first_off_by_default_not_in_dump():
    from open_guji_cv.steps.row_segment import RowSegmentParams
    assert "alt_cells_first" not in RowSegmentParams(cut_judge="rule").model_dump()
    assert RowSegmentParams(cut_judge="rule", alt_cells_first=True).model_dump()["alt_cells_first"] is True


def test_alt_text_ok_count_slack():
    from types import SimpleNamespace as NS
    from open_guji_cv.steps.align_ref import AlignRefParams, _alt_text_ok
    hi, lo = NS(cov=0.99, cand_variants=[]), NS(cov=0.5, cand_variants=[])
    main, alt = [hi] * 12 + [lo] * 11, [hi] * 12 + [lo] * 17      # 01 30:7：主 12/23、备选 12/29
    assert not _alt_text_ok(main, alt)                             # 按占比：0.41 < 0.52 - 0.05
    assert _alt_text_ok(main, alt, 1) and _alt_text_ok(main, [hi] * 11 + [lo] * 18, 1)
    assert not _alt_text_ok(main, [hi] * 10 + [lo] * 19, 1)
    assert "alt_text_count_slack" not in AlignRefParams().model_dump()
    assert AlignRefParams(alt_text_count_slack=1).model_dump()["alt_text_count_slack"] == 1


def test_row_segment_alt_cells_table(tmp_path, monkeypatch):
    """表里带 cells 的行 → 这列多出一份整列写定的备选（带 alt_cells 标记，夹注 a/b 照写）；col_h 对不上不出。"""
    from open_guji_cv.core.spec import column_key
    from open_guji_cv.core.step import STEPS, RunContext
    from open_guji_cv.steps.row_segment import ALT_CELLS_FLAG, RowSegmentParams
    book = make_book(expected_cols=4, chars_per_line=21)
    ctx, out = run_keben_chain(tmp_path, monkeypatch, book=book, through="row_segment", h=2000,
                               n_cols=4, w=500, period=100, col_n_chars={4: 3, 3: 7, 2: 12, 1: 5})
    col = next(c for c in out["cells"].columns if c.ok and len(c.cells) > 3)
    h = ctx.image("column_image", column_key(1, col.col)).shape[0]
    x0, x1 = col.content_x
    xm = (x0 + x1) / 2
    cells = [{"slot": 1, "sub": None, "kind": "char", "x0": x0, "x1": x1, "y0": 0, "y1": 150},
             {"slot": 2, "sub": "a", "kind": "jiazhu_a", "x0": xm, "x1": x1, "y0": 150, "y1": 220},
             {"slot": 2, "sub": "b", "kind": "jiazhu_b", "x0": x0, "x1": xm, "y0": 150, "y1": 220},
             {"slot": 3, "sub": None, "kind": "char", "x0": x0, "x1": x1, "y0": 220, "y1": 400}]

    def run(col_h):
        t = tmp_path / f"cells_{col_h}.jsonl"
        t.write_text(json.dumps({"vol": book.id, "page": 1, "col": col.col, "col_h": col_h, "cells": cells}) + "\n",
                     encoding="utf-8")
        p = RowSegmentParams(cut_judge="rule", alt_cuts=str(t))
        c2 = RunContext(ctx.book, ctx.store, ctx.cache, params={"row_segment": p}, log=lambda s: None)
        return STEPS["row_segment"].run_page(c2, 1)["cells"]

    got = run(h)
    alt = [c for c in got.alt_columns if c.col == col.col]
    assert len(alt) == 1 and ALT_CELLS_FLAG in alt[0].flags
    assert [(x.slot, x.sub) for x in alt[0].cells] == [(1, None), (2, "a"), (2, "b"), (3, None)]
    assert [c.cells for c in got.columns] == [c.cells for c in out["cells"].columns]     # 主切法不动
    assert not [c for c in run(h + 50).alt_columns if c.col == col.col]                 # 列图高变了不套


def test_alt_note_region_pick():
    """seed_admit.alt_note_region：备选把主切法并成大字的小注劈开了，小注范围外不更差就换（脉经 01 40:3「即穴也太淵」）。"""
    from types import SimpleNamespace as NS
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import ALT_ADMIT_MIN_GAIN, _pick_alt_cols, _note_spans

    def rec(s, sub, ok, ch="甲"):
        return AdmitRec(id=f"b:1:1:{s}{sub or ''}", slot=s, sub=sub, admit=ok, char=ch if ok else None,
                        channel="match_ref" if ok else None)

    def ch(s, sub, y0, y1):
        return NS(slot=s, sub=sub, bbox_page=(0, y0, 10, y1), patch_key="k")
    # 主切法：1–3 大字放行，4、5 是并成大字的小注（待审）
    main = PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[rec(1, None, 1), rec(2, None, 1), rec(3, None, 1),
                                                                rec(4, None, 0), rec(5, None, 0)])])
    cm = NS(columns=[NS(col=1, chars=[ch(s, None, 100 * s - 100, 100 * s) for s in range(1, 6)])])
    # 备选：1–3 同，4a/4b/5a/5b 小注，待审 3 格（比主切法多 1）
    alt = PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[rec(1, None, 1), rec(2, None, 1), rec(3, None, 1),
                                                               rec(4, "a", 1, "乙"), rec(4, "b", 0), rec(5, "a", 0),
                                                               rec(5, "b", 0)])])
    ca = NS(columns=[NS(col=1, chars=[ch(s, None, 100 * s - 100, 100 * s) for s in range(1, 4)]
                        + [ch(4, "a", 300, 400), ch(4, "b", 300, 400), ch(5, "a", 400, 500), ch(5, "b", 400, 500)])])
    ref = PageAlignRef(page=1)
    assert ALT_ADMIT_MIN_GAIN >= 1
    assert _note_spans(ca, 1) == [(300, 500)]
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca) == []                     # 缺省关：待审多了不换
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == [1]
    # 主切法在小注范围里放出了备选没放的字：不换
    main.columns[0].chars[3] = rec(4, None, 1, "丙")
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == []
    main.columns[0].chars[3] = rec(4, None, 0)
    # 小注范围外备选待审多了：不换
    alt.columns[0].chars[2] = rec(3, None, 0)
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == []
    alt.columns[0].chars[2] = rec(3, None, 1)
    # 主切法这里本来就认出了小注：照常比，不走这条
    cm.columns[0].chars[3] = ch(4, "a", 300, 400)
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == []


def test_alt_note_region_param_off_by_default_not_in_dump():
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    assert "alt_note_region" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(alt_note_region=True).model_dump()["alt_note_region"] is True


def test_alt_big_region_pick():
    """alt_note_region 反方向：主切法把大字劈成 a/b、备选同处一个放行的大字格（脉经 01 41:1「脉」→「永」「月」）。"""
    from types import SimpleNamespace as NS
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit, PageAlignRef
    from open_guji_cv.steps.seed_admit import _pick_alt_cols

    def rec(s, sub, ok, ch="甲"):
        return AdmitRec(id=f"b:1:1:{s}{sub or ''}", slot=s, sub=sub, admit=ok, char=ch if ok else None,
                        channel="match_ref" if ok else None)

    def ch(s, sub, y0, y1):
        return NS(slot=s, sub=sub, bbox_page=(0, y0, 10, y1), patch_key="k")
    main = PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[rec(1, None, 1), rec(2, "a", 1, "永"), rec(2, "b", 1, "月"),
                                                                rec(3, None, 1)])])
    cm = NS(columns=[NS(col=1, chars=[ch(1, None, 0, 100), ch(2, "a", 100, 200), ch(2, "b", 105, 195),
                                      ch(3, None, 200, 300)])])
    alt = PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[rec(1, None, 1), rec(2, None, 1, "脉"), rec(3, None, 1)])])
    ca = NS(columns=[NS(col=1, chars=[ch(1, None, 0, 100), ch(2, None, 100, 200), ch(3, None, 200, 300)])])
    ref = PageAlignRef(page=1)
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca) == []
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == [1]
    alt.columns[0].chars[1] = rec(2, None, 0)                    # 备选那个大字没放行：不换
    assert _pick_alt_cols([1], main, alt, ref, ref, cm, ca, note_region=True) == []
