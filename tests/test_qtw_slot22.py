"""overview#202：全唐文列末框线成格、「二」「三」被横切成两格。

两件事同一个根子：全唐文四周雙邊，Step1 的 bottom 落在外粗框上，内框细线留在列窗底部，
把交接闸量的墨跨度撑长约半格 → `n_raised_hint` 多给一格 → Step3 在 22 个字里切 23 格，
要么框线自成一格（列末 slot 22 出「一」），要么把字内留白最干净的「二」「三」劈开。

- `column_gate._ink_span`：量跨度前剔掉两端的碎段与细横线；
- `cell_shrink._is_tail_frame_bar`：列末格只装着框线（紧框矮、横贯文字带、贴着列窗下界）→ empty。

冻结样本在 `tests/fixtures/qtw_slot22/`（生成脚本 `scripts/experiments/qtw_slot22/build_fixtures.py`，
每例目检过）：split = D #155 点名的横切例（改后整字那一格的紧框当标签）、gate_keep = 真多一字的列
（hint 必须留着）、tail = 框线格正例与「一」/四庫末字负例。
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from open_guji_cv.gates.column_gate import ColumnGateParams, _ink_span
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells
from open_guji_cv.steps.cell_shrink import _is_tail_frame_bar
from open_guji_cv.utils.row_boundaries import segment_column

FIX = Path(__file__).parent / "fixtures" / "qtw_slot22"
CASES = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))
P = ColumnGateParams(span_trim_ends=True)     # 全唐文书 yaml 的口径
P_OFF = ColumnGateParams()                    # 缺省（四庫各册）


def _img(case) -> np.ndarray:
    return cv2.imread(str(FIX / case["png"]), cv2.IMREAD_GRAYSCALE)


def _band(case):
    im = _img(case)
    b0, b1 = (int(v) for v in case["content_x"])
    band = im[:, b0:b1] < P.ink_threshold
    return band, band.mean(axis=1)


def _hint(span: float | None, case) -> int:
    if span is None:
        return 0
    return max(0, min(int(span / case["period"] - case["n_body_slots"] + P.span_margin), P.max_raised_hint))


# ── 交接闸：跨度剔端 ────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES["split"], ids=lambda c: c["id"])
def test_split_column_loses_the_false_hint(case):
    band, prof = _band(case)
    ys = np.flatnonzero(prof > P.span_ink)
    raw = _hint(float(ys[-1] - ys[0]), case)
    assert raw >= 1, "样本失效：旧口径下这一列本来就不多给格"
    assert _hint(_ink_span(band, prof, case["period"], P), case) == 0


@pytest.mark.parametrize("case", CASES["gate_keep"], ids=lambda c: c["id"])
def test_real_raised_column_keeps_its_hint(case):
    """四庫 vol01 p50c5「上諭」真抬头：缺省口径（不剔）下 hint 照旧是 1。
    开了剔端它会掉成 0——这正是开关缺省关、只给全唐文开的原因（见 column_gate._ink_span）。"""
    band, prof = _band(case)
    p = P if case["trim"] else P_OFF
    assert _hint(_ink_span(band, prof, case["period"], p), case) == case["hint"]


def _synthetic_band(runs, w=300, h=4600):
    band = np.zeros((h, w), dtype=bool)
    for y0, y1, x0, x1 in runs:
        band[y0:y1, x0:x1] = True
    return band


def test_ink_span_drops_thin_full_width_rule_and_specks():
    # 字 150–4400；底部一条横贯的细线（厚 18 行），线下两行碎屑
    band = _synthetic_band([(150, 330, 60, 240), (4250, 4400, 50, 250),
                            (4460, 4478, 0, 300), (4500, 4502, 0, 120)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) == 4400 - 1 - 150


def test_ink_span_keeps_a_real_yi_at_the_column_end():
    # 列末真「一」：矮（30 行）但只占带宽 0.6，不横贯
    band = _synthetic_band([(150, 330, 60, 240), (4430, 4460, 60, 240)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) == 4460 - 1 - 150


def test_ink_span_drops_a_top_rule_too():
    band = _synthetic_band([(5, 20, 0, 300), (150, 330, 60, 240), (4250, 4400, 50, 250)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) == 4400 - 1 - 150


def test_ink_span_keeps_everything_when_only_junk():
    # 两端都是线、中间没字：剔到只剩一段就停，不返回空
    band = _synthetic_band([(5, 20, 0, 300), (4460, 4478, 0, 300)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) is not None


def test_ink_span_does_not_nibble_a_fragmented_char():
    # 细笔画的字在行墨门槛下碎成几段（每段 < 0.1 格、间隔 6 行）：不孤立，一段都不剔
    band = _synthetic_band([(150, 330, 60, 240), (4300, 4315, 60, 240), (4321, 4336, 60, 240),
                            (4342, 4357, 60, 240), (4363, 4378, 60, 240)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) == 4378 - 1 - 150


def test_ink_span_trim_is_capped():
    # 末端连着三条细线、合起来超过半格：剔到超上限的那一条就停
    band = _synthetic_band([(150, 330, 60, 240), (4000, 4150, 60, 240), (4200, 4215, 0, 300),
                            (4250, 4265, 0, 300), (4300, 4315, 0, 300)])
    assert _ink_span(band, band.mean(axis=1), 200.0, P) == 4215 - 1 - 150   # 第三条（4200）会超，留下


def test_ink_span_default_off_is_the_old_raw_span():
    band = _synthetic_band([(150, 330, 60, 240), (4250, 4400, 50, 250), (4460, 4478, 0, 300)])
    prof = band.mean(axis=1)
    ys = np.flatnonzero(prof > P_OFF.span_ink)
    assert _ink_span(band, prof, 200.0, P_OFF) == float(ys[-1] - ys[0])


# ── Step3：不多给那一格时，DP 不再劈字 ─────────────────────────────────

@pytest.mark.parametrize("case", CASES["split"], ids=lambda c: c["id"])
def test_dp_keeps_the_split_char_whole(case):
    r = segment_column(_img(case), period=case["period"], n_body_slots=case["n_body_slots"], n_raised=0,
                       border_top=case["border_top"], border_bottom=case["border_bottom"],
                       ref_w=case["ref_w"], top_slack=case["top_slack"],
                       content_x=tuple(case["content_x"]))
    assert r is not None
    _, y0, _, y1 = case["bbox"]
    inside = [b for b in r.boundaries if y0 + 3 < b < y1 - 3]
    assert not inside, f"「{case['char']}」({y0:.0f}–{y1:.0f}) 又被 {inside} 劈开"


# ── Step4：列末框线格 ────────────────────────────────────────────────

def _cc(case) -> ColumnCells:
    cells = [CellRec(slot=p, pos=p, y0=0, y1=1, x0=0, x1=1, kind="char", order=p)
             for p in range(1, case["last_pos"] + 1)]
    return ColumnCells(col=1, ok=True, n_body_slots=case["last_pos"], period=case["period"],
                       content_x=tuple(case["content_x"]), border_bottom=case["border_bottom"],
                       cells=cells)


@pytest.mark.parametrize("case", CASES["tail"], ids=lambda c: c["id"])
def test_tail_frame_bar(case):
    assert _is_tail_frame_bar(case["pos"], "char", tuple(case["bbox"]), _cc(case)) is case["frame"], case["why"]


def test_tail_frame_bar_only_on_the_last_cell():
    case = next(c for c in CASES["tail"] if c["frame"])
    moved = dict(case, last_pos=case["pos"] + 1)
    assert not _is_tail_frame_bar(case["pos"], "char", tuple(case["bbox"]), _cc(moved))


def test_tail_frame_bar_ignores_empty_cells():
    case = next(c for c in CASES["tail"] if c["frame"])
    assert not _is_tail_frame_bar(case["pos"], "empty", tuple(case["bbox"]), _cc(case))
