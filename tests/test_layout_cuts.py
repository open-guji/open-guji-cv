"""格位表人定格线 `cuts`（row_segment._layout_cuts）的校验：格数照线、列图高对不上或线乱序就不套。"""
from open_guji_cv.steps.row_segment import LAYOUT_CUTS_H_TOL, _layout_cuts


def _row(**kw):
    r = {"slots": [1, 2, 3], "notes": [], "half": [], "raised": 0, "col_h": 1000,
         "cuts": [0, 200, 400, 600, 800, 1000]}
    r.update(kw)
    return r


def test_ok_gives_lines():
    assert _layout_cuts(_row(), 1000, 0) == [0.0, 200.0, 400.0, 600.0, 800.0, 1000.0]


def test_col_h_tolerance():
    assert _layout_cuts(_row(), 1000 + LAYOUT_CUTS_H_TOL, 0) is not None
    assert _layout_cuts(_row(), 1000 + LAYOUT_CUTS_H_TOL + 1, 0) is None


def test_missing_col_h_or_bad_order():
    r = _row()
    del r["col_h"]
    assert _layout_cuts(r, 1000, 0) is None
    assert _layout_cuts(_row(cuts=[0, 200, 200, 600]), 1000, 0) is None


def test_slots_must_fit():
    # 5 格装不下表的 6 号格
    assert _layout_cuts(_row(slots=[1, 6]), 1000, 0) is None
    # 抬头 1 格时正文只剩 4 格
    assert _layout_cuts(_row(slots=[-1, 1, 5]), 1000, 1) is None
    assert _layout_cuts(_row(slots=[-1, 1, 4]), 1000, 1) is not None
