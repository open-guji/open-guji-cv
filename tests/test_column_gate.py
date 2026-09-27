# -*- coding: utf-8 -*-
"""Step2→3 交接闸的判据分层。

守住 2026-09-03 的那次改动：**列宽偏离是列级判据，不是页级**。
它逐列算得出，却曾被放在页级拒因里 —— 一列坏就整页 9 列作废。
实证见 doc/step3_error_survey.md 乙类（vol01/42 八列完好只因 c9 坏而全废）。

2026-09-20 重写。原先九条用例都是**扫工作区里碰巧跑出来的 column_gate 产物**，
在里头捞「有没有一列被 L1c 拦了」「有没有一页列数不对」来断言，捞不到就 skip。
这样写的三个毛病，这一轮全撞上了：

1. **跑批一变结论就变**，测试红了说不清是代码坏了还是这次跑批的数据不同；
2. **云端一条都跑不了**（原图与产物都在工作区），九条全 skip；
3. **断言会悄悄失效**——`test_wide_column_blocks_only_itself` 查的是
   `"L1c" in column.reject`，而 L1c 在 2026-09-19 已从 block 降级成 flag，
   拒因里永远不会再有它；`test_page_level_still_rejects_wrong_column_count`
   查的是拒因含「只探出」。两条都是**在本机也永远进不到断言**的死代码。

现在每条用例自己合成出要测的那一种版式（`helpers.synth_page` 图与 `Borders`
同源生成），跑真的 Step2 + 闸2 链路。「period 落在 100~125」这类**对真书数据
的质量断言**不再放在这里——那是评测该管的（`guji eval run`），测试管的是
「判据分层对不对」。
"""

from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import (blank_page, column_xs, make_book, make_gate1, run_border_to_column_gate,
                     skip_gate1, synth_page)

PAGE = 1
NCOLS = 9


def _uneven_page(shift: float = 40.0):
    """把一条界行挪开，造出「一列特别宽、邻列特别窄」——L1c 要认的就是这个形态。"""
    xs = column_xs(n_cols=NCOLS)
    xs[5] += shift
    return synth_page(xs=xs)


def _width_flags(col) -> list[str]:
    return [f for f in col.flags if f.startswith("column_width")]


def test_wide_column_is_flagged_on_itself_not_on_the_page(tmp_path):
    """列宽偏离只标本列，页级既不拒也不提它。

    这是 2026-09-03 那一刀的核心：判据逐列算得出，就该逐列表达。
    （2026-09-19 它又从 block 降成 flag，所以这里查的是 flags 不是 reject——
    降级本身由 `test_wide_column_does_not_block_the_column` 单独守。）
    """
    gray, borders = _uneven_page()
    _, out = run_border_to_column_gate(tmp_path, gray, borders)
    gm = out["gate_manifest"]

    assert gm.admitted, f"页级不该因单列宽度而拒绝：{gm.reject}"
    assert not any("列宽" in r or r.startswith("column_width") for r in gm.reject), \
        f"页级拒因里出现了列宽：{gm.reject}"
    assert not any("列宽" in f or f.startswith("column_width") for f in gm.flags), \
        f"页级 flag 里出现了列宽：{gm.flags}"

    flagged = [c.col for c in gm.columns if _width_flags(c)]
    assert flagged, "挪开一条界行之后没有任何一列被判宽度偏离——判据没生效？"
    assert len(flagged) < len(gm.columns), "所有列都被判偏离，那就不是逐列判据了"


def test_wide_column_does_not_block_the_column(tmp_path):
    """宽度偏离是 flag 不是 block（2026-09-19 降级）。

    降级的理由记在 `column_gate.py` L1c 那段：vol02 被它拦下的 4 列逐列看图
    全是干净单列，强行送进 Step3 全部有解。这里守的是**处置**——判词里
    「多半」这种口气不足以丢掉一整列。
    """
    gray, borders = _uneven_page()
    _, out = run_border_to_column_gate(tmp_path, gray, borders)
    for c in out["gate_manifest"].columns:
        if _width_flags(c):
            assert c.admitted, f"c{c.col} 只是宽度偏离，不该被拦：{c.reject}"
            assert not any(r.startswith("column_width") for r in c.reject)


def test_page_priors_are_computed_from_geometrically_normal_columns(tmp_path):
    """页级 period / ref_w 由几何正常的列算出——异常列剔除后仍算得出来。

    只钉「算得出、且宽度基准取自正常列而不是被那条宽列拉偏」，不钉具体数值：
    数值是这页合成版式的函数，写死等于把 fixture 的参数抄两遍。
    """
    even_gray, even_borders = synth_page(n_cols=NCOLS)
    _, even = run_border_to_column_gate(tmp_path / "even", even_gray, even_borders)
    uneven_gray, uneven_borders = _uneven_page()
    _, uneven = run_border_to_column_gate(tmp_path / "uneven", uneven_gray, uneven_borders)

    a, b = even["gate_manifest"], uneven["gate_manifest"]
    assert a.period is not None and a.ref_w is not None
    assert b.period is not None and b.ref_w is not None
    assert b.period == a.period, "剔掉宽度异常列之后 period 不该变"
    assert abs(b.ref_w - a.ref_w) <= 5, \
        f"ref_w 被那条宽列拉偏了：{b.ref_w} vs {a.ref_w}"


def test_page_level_still_rejects_wrong_column_count(tmp_path):
    """列数不对仍是页级问题——整页的列编号和窗口一起错位，单列救不回来。"""
    gray, borders = synth_page(n_cols=NCOLS - 2)     # 只切出 7 列
    book = make_book(expected_cols=NCOLS)
    _, out = run_border_to_column_gate(
        tmp_path, gray, borders, book=book,
        gate1=make_gate1(PAGE, n_cols=NCOLS - 2, expected_cols=NCOLS))
    gm = out["gate_manifest"]
    assert not gm.admitted
    assert any(r.startswith("column_count") for r in gm.reject), gm.reject
    assert all(not c.admitted for c in gm.columns), "列数不对时整页都该拒绝"


def test_skip_page_reject_says_page_type_not_column_count(tmp_path):
    """闸1 判 skip 的页，闸2 的拒因要说页型，不要报「只探出 0 列」——
    列数是症状，页型才是原因，报错报症状会把人引去查切列算法。"""
    _, out = run_border_to_column_gate(
        tmp_path, blank_page(), synth_page(n_cols=NCOLS)[1],
        gate1=skip_gate1(PAGE, expected_cols=NCOLS))
    gm = out["gate_manifest"]
    assert not gm.admitted
    assert any(r.startswith("page_type_skip") for r in gm.reject), gm.reject
    assert not any(r.startswith("column_count") for r in gm.reject), gm.reject


def test_top_flush_column_gets_slack_and_plain_columns_do_not(tmp_path):
    """版框平齐但顶端有字墨的**顶格列**要拿到 top_slack，普通正文列不能拿。

    钉住 2026-09-03 的 A2 第一刀。原先只有 `raised`（Step1 探到抬头**框**、
    版框有台阶）才给 slack，而这批书里更常见的是版框平齐、字从版框内顶端
    起写——`raised=False`、`border_top_in_column=0`、`top_slack=0`，DP 首锚点
    窗口开不上去，首字被压在格顶。vol01/141 c7「諭旨」是实锤。

    「普通列不能拿」这半边同样要守：全命中等于没判据（版框条下沿的毛边一度
    就被认成顶格，vol01/141 c1/c3 各拿到 58px slack、Step3 在首格切出假 char）。
    """
    # 左起三列顶格写，其余离上版框 40px。列号是右起，所以顶格的是 c7~c9。
    gray, borders = synth_page(top_gap=40, col_top_gap={1: 0, 2: 0, 3: 0})
    _, out = run_border_to_column_gate(tmp_path, gray, borders)
    gm = out["gate_manifest"]
    flush = {c.col for c in gm.columns if c.top_slack > 0}
    assert flush == {7, 8, 9}, f"顶格判定跑偏了：{[(c.col, c.top_slack) for c in gm.columns]}"
    assert all(not c.raised for c in gm.columns), "这页版框是平齐的，不该判成抬头框型"


def test_bottom_bound_reaches_past_the_frame_line(tmp_path):
    """交给 Step3 的下界要落在版框线**之外**，否则末字够不到。

    钉住 2026-09-03 的 A4 一刀。Step3 的 candN 窗口上界就是这个 border_bottom，
    传版框线的话，末字只要压着版框写、末边界就永远够不到它——实测 dev_set
    216 列中 147 列（68%）真末墨超出版框线，末格 y1 比真末墨低中位 11px，
    slot 21 因此占了 R4 被切总数的 57%。
    """
    gray, borders = synth_page(n_cols=NCOLS)
    _, out = run_border_to_column_gate(tmp_path, gray, borders)
    gm, wins = out["gate_manifest"], out["column_windows"]
    assert gm.columns
    for gc in gm.columns:
        wc = next(x for x in wins.columns if x.col == gc.col)
        assert gc.border_bottom > wc.border_bottom_in_column, \
            f"c{gc.col} 下界没越过版框线"
        assert gc.border_bottom <= wc.warped_size[1], f"c{gc.col} 下界超出列图"


def test_n_raised_hint_is_per_column_not_page_wide(tmp_path):
    """「抬头多一个字」是逐列的，闸要按墨跨度逐列给出 hint。

    钉住 2026-09-03 的 A2 收尾。`n_raised` 原先只有页级参数一个来源，
    而同一页上有的抬头列多一格、有的只是整体上挪（vol01/33 四个抬头列
    实测 3 个多一字、1 个不多）。给不出逐列值时 DP 只能在 21 格里硬塞
    22 个字，唯一可行解是**丢掉首字**。

    合成：整页每列 10 个字，只有左起第一列（= c9）顶上多写一个。
    """
    gray, borders = synth_page(period=120, n_chars=10, top_gap=120,
                               col_top_gap={1: 0}, col_n_chars={1: 11})
    _, out = run_border_to_column_gate(
        tmp_path, gray, borders,
        book=make_book(expected_cols=NCOLS, chars_per_line=10))
    hints = {c.col: c.n_raised_hint for c in out["gate_manifest"].columns}
    assert hints[9] == 1, f"多一个字的那列没拿到 hint：{hints}"
    assert all(v == 0 for k, v in hints.items() if k != 9), \
        f"hint 不是逐列的，别的列也命中了：{hints}"


def test_n_raised_hint_is_capped(tmp_path):
    """跨度估歪时 hint 不许暴走——上限由 `max_raised_hint` 兜着。"""
    from open_guji_cv.gates.column_gate import ColumnGateParams

    gray, borders = synth_page(period=120, n_chars=10)
    _, out = run_border_to_column_gate(
        tmp_path, gray, borders,
        book=make_book(expected_cols=NCOLS, chars_per_line=1))   # 基准故意给错
    cap = ColumnGateParams().max_raised_hint
    for c in out["gate_manifest"].columns:
        assert c.n_raised_hint <= cap, f"c{c.col} hint={c.n_raised_hint} 超过上限 {cap}"


# ── 夹注列豁免（2026-09-17）────────────────────────────────


def _synth_column(h: int, w: int, period: float, seam: int | None) -> np.ndarray:
    """合成列图：`seam=None` 出一列居中大字，给了就出双列小字。"""
    img = np.full((h, w), 255, dtype=np.uint8)
    n = int(h / period)
    for k in range(n):
        y0, y1 = int(k * period) + 8, int((k + 1) * period) - 8
        if seam is None:
            img[y0:y1, int(w * 0.20):int(w * 0.80)] = 0
        else:
            img[y0:y1, 6:seam - 4] = 0
            img[y0:y1, seam + 4:w - 6] = 0
    return img


def test_jiazhu_column_frac_separates_jiazhu_from_normal_column():
    """豁免判据的分辨力：夹注列该高、正文列该 0。

    真实标定（bxgb 全书 931 列）：正文列中位 0.000 / p99 0.048，
    三条真夹注列 0.44 / 0.76 / 1.00 —— 中间空一大档，门槛取 0.25。
    """
    from open_guji_cv.gates.column_gate import jiazhu_column_frac

    h, w, period = 1470, 110, 70.0
    normal = _synth_column(h, w, period, seam=None)
    jiazhu = _synth_column(h, w, period, seam=w // 2)
    f_normal = jiazhu_column_frac(normal, (0.0, float(w)), 0.0, float(h), period, float(w))
    f_jiazhu = jiazhu_column_frac(jiazhu, (0.0, float(w)), 0.0, float(h), period, float(w))
    assert f_normal < 0.25 <= f_jiazhu


def test_jiazhu_column_frac_zero_without_period():
    """period 缺失时不豁免——宁可照旧拒，也不要凭空放行。"""
    from open_guji_cv.gates.column_gate import jiazhu_column_frac

    img = _synth_column(700, 110, 70.0, seam=55)
    assert jiazhu_column_frac(img, (0.0, 110.0), 0.0, 700.0, None, 110.0) == 0.0
