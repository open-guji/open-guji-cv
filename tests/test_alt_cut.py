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

