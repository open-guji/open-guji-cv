# -*- coding: utf-8 -*-
"""窄对合并（Step1 后处理，`books/siku_zongmu/column_pair_merge`；overview GUJI-155／208ax）。

只用纯内存构造的列宽表（`helpers.make_borders(xs=…)`），不依赖真书；列宽形态取自七册 1191 页
扫描里的真页（vol04 p80／p217、vol07 p128／p130 是正例；vol05 p55／p123、vol04 p63、p216／p218、
扉页是反例）——数是形态，不是 fixture 文件。"""
from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import blank_page, make_book, make_borders, make_ctx
from open_guji_cv.core.step import STEPS
from open_guji_cv.books.siku_zongmu import column_pair_merge as cpm

PAGE = 1


def _xs(widths, start=100.0):
    out = [start]
    for w in widths:
        out.append(out[-1] + w)
    return out


# 真页的列宽形态（右→左，px）
P217 = [187, 89, 92, 184, 181, 181, 186, 185, 200]     # 线穿字心，窄对 c2＋c3
P80 = [184, 185, 182, 185, 83, 101, 187, 183, 179]     # 窄对 c5＋c6
P128 = [187, 180, 180, 183, 93, 91, 180, 180, 182]     # 窄对 c5＋c6
P130 = [191, 67, 116, 181, 184, 186, 180, 179, 182]    # 夹注缝上的线，窄对 c2＋c3
P55 = [180, 181, 183, 186, 185, 185, 187, 184, 59]     # 反例：最左缘单窄列
P123 = [181, 183, 181, 178, 188, 184, 181, 183, 84]    # 反例：边缘
P63 = [117, 182, 183, 179, 188, 186, 182, 183, 181]    # 反例：另一端边缘
P216 = [188, 183, 183, 184, 184, 366, 187, 183, 368]   # 反例：两倍宽
FRONT = [80, 142, -65, 250]                             # 反例：扉页，列宽乱（含负宽）


@pytest.mark.parametrize("widths,pair", [(P217, 2), (P80, 5), (P128, 5), (P130, 2)])
def test_real_pair_pages_trigger(widths, pair):
    assert cpm.find_narrow_pair(_xs(widths)) == pair


@pytest.mark.parametrize("widths", [P55, P123, P63, P216, FRONT])
def test_counter_example_pages_do_not_trigger(widths):
    assert cpm.find_narrow_pair(_xs(widths)) is None


def test_edge_pair_never_triggers():
    """窄对在页首／页末（任一条是第 1 列或最末列）一律不触发——边缘窄列重探后也「干净」，但丢真列。"""
    assert cpm.find_narrow_pair(_xs([89, 92, 184, 181, 181, 186, 185, 200, 190])) is None   # c1＋c2
    assert cpm.find_narrow_pair(_xs([190, 184, 181, 181, 186, 185, 200, 89, 92])) is None   # c8＋c9


def test_two_pairs_or_dirty_rest_do_not_trigger():
    assert cpm.find_narrow_pair(_xs([180, 89, 92, 180, 83, 101, 180, 180, 180])) is None      # 两对：页本身有毛病
    assert cpm.find_narrow_pair(_xs([180, 89, 92, 130, 181, 181, 186, 185, 200])) is None     # 其余列有 0.72 倍的异常
    assert cpm.find_narrow_pair(_xs([187, 89, 150, 184, 181, 181, 186, 185, 200])) is None    # 一条不够窄
    assert cpm.find_narrow_pair(_xs([187, 60, 60, 184, 181, 181, 186, 185, 200])) is None     # 和只有 0.67 倍，不是一列


def test_accept_requires_line_set_minus_one_and_clean():
    old = _xs(P217)
    new_ok = [x for i, x in enumerate(old) if i != 2]                    # 去掉第 3 条线（c2、c3 之间）
    assert cpm.accept_merge(old, new_ok, 8)
    assert not cpm.accept_merge(old, new_ok, 9)                          # 列数不对
    moved = [x + (20 if i == 4 else 0) for i, x in enumerate(new_ok)]   # 一条线挪了 20 px：不是旧线集的子集
    assert not cpm.accept_merge(old, moved, 8)
    dirty = [x for i, x in enumerate(old) if i != 4]                     # 去掉的是另一条线：留下窄对，不干净
    assert not cpm.accept_merge(old, dirty, 8)


def test_merge_does_not_call_detect_when_not_triggered():
    calls = []
    res = make_borders(xs=_xs(P55)).to_result()
    out, cols, pair = cpm.merge_narrow_pair(res, 9, lambda n: calls.append(n))
    assert out is res and cols == 9 and pair is None and not calls


def test_merge_triggered_but_rejected_keeps_original():
    old = make_borders(xs=_xs(P217)).to_result()
    bad = make_borders(xs=_xs([187, 89, 92, 184, 181, 181, 186, 385])).to_result()   # 重探结果有异常列
    out, cols, pair = cpm.merge_narrow_pair(old, 9, lambda n: bad)
    assert out is old and cols == 9 and pair is None


def test_merge_triggered_and_accepted():
    old = make_borders(xs=_xs(P217)).to_result()
    xs2 = [x for i, x in enumerate(_xs(P217)) if i != 2]
    new = make_borders(xs=xs2).to_result()
    seen = []
    out, cols, pair = cpm.merge_narrow_pair(old, 9, lambda n: (seen.append(n), new)[1])
    assert out is new and cols == 8 and pair == 2 and seen == [8]


# ── Step1 整合：开关与产物字节 ────────────────────────────────────────────

def _run_step(tmp_path, monkeypatch, widths, *, on, redetect=None):
    """用桩替掉 `detect_borders`：n 列→给定线集；返回 (borders, line_index) 的 JSON 文本。"""
    import open_guji_cv.steps.border_detect as bd

    xs9 = _xs(widths)
    table = {9: make_borders(xs=xs9).to_result()}
    if redetect is not None:
        table[8] = make_borders(xs=redetect).to_result()
    seen = []

    def fake(gray, expected_cols, **kw):
        seen.append(expected_cols)
        return table[expected_cols]

    monkeypatch.setattr(bd, "detect_borders", fake)
    book = make_book(expected_cols=9)
    ctx = make_ctx(tmp_path, book, raw={PAGE: blank_page(1000, 1400)})
    from open_guji_cv.steps.border_detect import BorderDetectParams
    ctx.params["border_detect"] = BorderDetectParams(merge_narrow_pair=on, pitch_rescue=False)   # 只测窄对合并
    out = STEPS["border_detect"].run_page(ctx, PAGE)
    return out, seen


def _dump(out):
    return {k: v.model_dump_json() for k, v in out.items()}


@pytest.mark.parametrize("widths", [P55, P123, P63, P216, [180] * 9])
def test_untriggered_pages_are_byte_identical_with_switch_on(tmp_path, monkeypatch, widths):
    off, _ = _run_step(tmp_path / "a", monkeypatch, widths, on=False)
    on, seen = _run_step(tmp_path / "b", monkeypatch, widths, on=True)
    assert _dump(on) == _dump(off)
    assert seen == [9]                      # 没触发就没有第二次探测


def test_switch_off_never_merges_even_on_pair_page(tmp_path, monkeypatch):
    xs2 = [x for i, x in enumerate(_xs(P217)) if i != 2]
    out, seen = _run_step(tmp_path, monkeypatch, P217, on=False, redetect=xs2)
    assert seen == [9] and out["borders"].expected_cols == 9 and len(out["borders"].verticals) == 10


def test_pair_page_merged_when_switch_on(tmp_path, monkeypatch):
    xs2 = [x for i, x in enumerate(_xs(P217)) if i != 2]
    out, seen = _run_step(tmp_path, monkeypatch, P217, on=True, redetect=xs2)
    assert seen == [9, 8]
    b = out["borders"]
    assert b.expected_cols == 8 and len(b.verticals) == 9
    li = out["line_index"]
    assert len(li.lines) == 8
    merged = [ln for ln in li.lines if any(f.startswith("pair_merged") for f in ln.flags)]
    assert [ln.col for ln in merged] == [2]
    assert all(not any(f.startswith("pair_merged") for f in ln.flags) for ln in li.lines if ln.col != 2)


# ── 闸要认「合并后列数＝expected−1」 ──────────────────────────────────────

def _line_index_with_flag(xs, flag=True):
    from open_guji_cv.products.kinds.line_index import LineIndex, LineRec
    lines = [LineRec(col=i + 1, kind="body", x0=xs[i], x1=xs[i + 1], y0=0.0, y1=1.0,
                     width=xs[i + 1] - xs[i],
                     flags=["pair_merged：测试"] if (flag and i == 1) else [])
             for i in range(len(xs) - 1)]
    return LineIndex(page=PAGE, width=1900, height=1400, em=None, pitch=None,
                     n_body=len(lines), lines=lines)


def test_border_detect_gate_accepts_merged_page(tmp_path):
    xs2 = [x for i, x in enumerate(_xs(P217, 60.0)) if i != 2]
    borders = make_borders(w=1900, xs=xs2)           # 8 列，expected_cols=8（Step1 记的）
    ctx = make_ctx(tmp_path, make_book(expected_cols=9), raw={PAGE: blank_page(1900, 1400)})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}",
                    {"borders": borders, "line_index": _line_index_with_flag(xs2)})
    m = STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]
    assert not any(r.startswith("column_count") for r in m.reject)
    assert m.expected_cols == 8 and m.n_cols == 8
    assert any(f.startswith("pair_merged") for f in m.flags)


def test_border_detect_gate_still_rejects_wrong_count_without_merge_flag(tmp_path):
    """没有 `pair_merged` 旗的页：8 列而书级 9 列，照旧 column_count 拒收——哪怕 `Borders.expected_cols`
    恰好也是 8（造数据的 `make_borders` 就这样；不能靠两个数相等去猜合并过）。"""
    borders = make_borders(w=1900, xs=_xs([180] * 8, 60.0))
    ctx = make_ctx(tmp_path, make_book(expected_cols=9), raw={PAGE: blank_page(1900, 1400)})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    m = STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]
    assert any(r.startswith("column_count") for r in m.reject)
    assert not any(f.startswith("pair_merged") for f in m.flags)


def test_column_gate_follows_gate1_expected_cols_on_merged_page(tmp_path):
    """闸2 按闸1 记的期望列数（合并页＝书级−1）判列数；闸1 没记少一列时照旧拒收。"""
    from helpers import make_gate1, run_border_to_column_gate, synth_page

    gray, borders = synth_page(n_cols=8)                         # 8 列页
    book = make_book(expected_cols=9)
    g1 = make_gate1(PAGE, n_cols=8, expected_cols=8)
    g1.flags.append("pair_merged：测试")
    _, merged = run_border_to_column_gate(tmp_path / "m", gray, borders, book=book, gate1=g1)
    assert not any(r.startswith("column_count") for r in merged["gate_manifest"].reject)
    _, plain = run_border_to_column_gate(
        tmp_path / "p", gray, borders, book=book,
        gate1=make_gate1(PAGE, n_cols=8, expected_cols=8))        # 没有 pair_merged 旗：照旧拒收
    assert any(r.startswith("column_count") for r in plain["gate_manifest"].reject)


# ── 产物不自洽（Elena 评审条件 5①）：有 pair_merged 旗，但列数对不上 ──────────

def _gate1_with_flag(tmp_path, xs, *, borders_expected, book_expected=9, gate_param=None):
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams
    borders = make_borders(w=1900, xs=xs).model_copy(update={"expected_cols": borders_expected})
    ctx = make_ctx(tmp_path, make_book(expected_cols=book_expected), raw={PAGE: blank_page(1900, 1400)})
    if gate_param is not None:
        ctx.params["border_detect_gate"] = BorderDetectGateParams(expected_cols=gate_param)
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}",
                    {"borders": borders, "line_index": _line_index_with_flag(xs)})
    return STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]


def test_gate1_flag_but_borders_expected_cols_disagrees_is_not_relaxed(tmp_path):
    """旗＋8 列，但 Step1 记的列数是 9（不自洽）：不放宽，仍按书级 9 列拒收，并留 `pair_merged_inconsistent`。"""
    m = _gate1_with_flag(tmp_path, _xs([180] * 8, 60.0), borders_expected=9)
    assert any(r.startswith("column_count") for r in m.reject) and m.expected_cols == 9
    names = [f.split("：")[0] for f in m.flags]
    assert "pair_merged_inconsistent" in names and "pair_merged" not in names


def test_gate1_flag_but_n_cols_equals_book_expected_only_flags(tmp_path):
    """旗＋9 列、Step1 记 8 列：列数本身没问题（9＝书级），不拒收，但留不自洽提示，不当合并页。"""
    m = _gate1_with_flag(tmp_path, _xs([180] * 9, 60.0), borders_expected=8)
    assert not any(r.startswith("column_count") for r in m.reject) and m.expected_cols == 9
    names = [f.split("：")[0] for f in m.flags]
    assert "pair_merged_inconsistent" in names and "pair_merged" not in names


def test_gate1_aligns_with_its_own_expected_cols_param(tmp_path):
    """合并页的期望＝**闸自己的**期望−1：闸参数设成 10 时，8 列合并页（Step1 记 8）对不上 9，不放宽。"""
    m = _gate1_with_flag(tmp_path, _xs([180] * 8, 60.0), borders_expected=8, gate_param=10)
    assert any(r.startswith("column_count") for r in m.reject)
    assert "pair_merged_inconsistent" in [f.split("：")[0] for f in m.flags]
    ok = _gate1_with_flag(tmp_path / "ok", _xs([180] * 8, 60.0), borders_expected=8, gate_param=9)
    assert not any(r.startswith("column_count") for r in ok.reject)
    assert "pair_merged" in [f.split("：")[0] for f in ok.flags]


def test_gate1_only_swallows_missing_line_index(tmp_path, monkeypatch):
    """`line_index` 缺失（FileNotFoundError）当没合并过；别的异常不吞。"""
    borders = make_borders(w=1900, xs=_xs([180] * 9, 60.0))
    ctx = make_ctx(tmp_path, make_book(expected_cols=9), raw={PAGE: blank_page(1900, 1400)})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})   # 没写 line_index
    STEPS["border_detect_gate"].run_page(ctx, PAGE)                                      # 不抛
    real = ctx.product

    def boom(kind, page):
        if kind == "line_index":
            raise ValueError("坏产物")
        return real(kind, page)

    monkeypatch.setattr(ctx, "product", boom)
    with pytest.raises(ValueError):
        STEPS["border_detect_gate"].run_page(ctx, PAGE)


def test_border_detect_gate_declares_line_index_as_optional_upstream():
    assert "line_index" in STEPS["border_detect_gate"].spec.optional_consumes
    assert "open_guji_cv.books.siku_zongmu.column_pair_merge" in STEPS["border_detect_gate"].spec.code_deps
    assert "open_guji_cv.books.siku_zongmu.column_pair_merge" in STEPS["column_gate"].spec.code_deps


def test_pair_merged_flag_helpers_do_not_confuse_inconsistent_with_merged():
    assert cpm.has_pair_merged(["x", "pair_merged：说明"])
    assert not cpm.has_pair_merged(["pair_merged_inconsistent：说明"])
    assert not cpm.has_pair_merged([])


# ── 端到端（Elena 评审条件 5②）：Step1 → 闸1 → Step2 → 闸2 连跑，8 列合并页放行 ──

def test_end_to_end_merged_page_passes_both_gates(tmp_path, monkeypatch):
    import open_guji_cv.steps.border_detect as bd
    from helpers import run_steps, synth_page
    from open_guji_cv.steps.border_detect import BorderDetectParams

    xs9 = _xs(P217, 60.0)
    xs8 = [x for i, x in enumerate(xs9) if i != 2]
    gray, _ = synth_page(w=1900, xs=xs8)                                  # 真的是 8 列的页
    table = {9: make_borders(w=1900, xs=xs9).to_result(), 8: make_borders(w=1900, xs=xs8).to_result()}
    monkeypatch.setattr(bd, "detect_borders", lambda g, expected_cols, **kw: table[expected_cols])
    ctx = make_ctx(tmp_path, make_book(expected_cols=9), raw={PAGE: gray}, monkeypatch=monkeypatch)
    ctx.params["border_detect"] = BorderDetectParams(merge_narrow_pair=True, pitch_rescue=False)   # 只测窄对合并

    out = run_steps(ctx, PAGE, ["border_detect", "border_detect_gate", "column_warp", "column_gate"])
    g1, g2 = out["border_detect_gate_manifest"], out["gate_manifest"]
    assert g1.admitted and g1.n_cols == 8 and g1.expected_cols == 8
    assert "pair_merged" in [f.split("：")[0] for f in g1.flags]
    assert len(g2.columns) == 8
    assert not any(r.startswith("column_count") for r in g2.reject)
    assert g2.admitted and all(c.admitted for c in g2.columns)


# ── 缺省关时不进参数 dump：没开的册 params_hash 与加字段前逐位相同（GUJI-572 移植） ─────────
def test_merge_narrow_pair_is_absent_from_dump_when_off():
    from open_guji_cv.steps.border_detect import BorderDetectParams
    assert "merge_narrow_pair" not in BorderDetectParams().model_dump()
    assert "merge_narrow_pair" not in BorderDetectParams(merge_narrow_pair=False).model_dump()
    assert BorderDetectParams(merge_narrow_pair=True).model_dump()["merge_narrow_pair"] is True


def test_params_hash_unchanged_by_the_new_field_when_off():
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.border_detect import BorderDetectParams
    on = params_hash(BorderDetectParams(merge_narrow_pair=True))
    off = params_hash(BorderDetectParams())
    assert on != off
    assert off == params_hash(BorderDetectParams(expected_cols=None, ink_threshold=128))
