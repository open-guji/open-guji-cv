"""人裁逐列抬头（`lookup.resolved_head_raise` → `border_detect.apply_head_raise_verdicts`）。"""
from open_guji_cv.steps.border_detect import apply_head_raise_verdicts
from open_guji_cv.books.siku_zongmu.border import HR_DEFAULT_PAIR_GAP
from open_guji_cv.seg.frame_types import BorderDetectionResult, HeadRaiseBorder, HLine, VLine


def _res(head_raise):
    # 平直版框：上 210、下 1890（21 格 × 80），4 列各 100 宽
    return BorderDetectionResult(
        width=500, height=2000, top=HLine(210.0, 0.0, "top"), bottom=HLine(1890.0, 0.0, "bottom"),
        verticals=[VLine(x_at_top=50.0 + 100.0 * i, slope=0.0) for i in range(5)],
        head_raise=list(head_raise))


def test_no_verdict_is_identity():
    res = _res([HeadRaiseBorder(col=1, inner_y=150.0, outer_y=120.0)])
    assert apply_head_raise_verdicts(res, {}, 21) == {}
    assert [h.col for h in res.head_raise] == [1]


def test_add_uses_same_page_raise_height():
    res = _res([HeadRaiseBorder(col=1, inner_y=150.0, outer_y=120.0),
                HeadRaiseBorder(col=2, inner_y=154.0, outer_y=126.0)])
    done = apply_head_raise_verdicts(res, {3: 1, 1: 1}, 21)
    assert done == {3: 1}                        # Step1 已认的列不动
    h = {x.col: x for x in res.head_raise}
    assert [x.col for x in res.head_raise] == [1, 2, 3]
    assert h[3].inner_y == 152.0 and h[3].outer_y == 152.0 - 29.0 and h[3].estimated
    assert h[1].inner_y == 150.0 and not h[1].estimated


def test_add_without_same_page_raise_uses_cell_height():
    res = _res([])
    assert apply_head_raise_verdicts(res, {2: 2}, 21, scale=0.5) == {2: 2}
    (h,) = res.head_raise
    assert h.col == 2 and h.inner_y == 210.0 - 2 * 80.0
    assert h.outer_y == h.inner_y - HR_DEFAULT_PAIR_GAP * 0.5


def test_no_removes_step1_raise_and_ignores_out_of_range():
    res = _res([HeadRaiseBorder(col=1, inner_y=150.0, outer_y=120.0),
                HeadRaiseBorder(col=2, inner_y=150.0, outer_y=120.0)])
    assert apply_head_raise_verdicts(res, {2: 0, 3: 0, 9: 1}, 21) == {2: 0}
    assert [h.col for h in res.head_raise] == [1]
