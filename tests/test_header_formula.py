"""题列套语放行 seed_admit.lane_header_formula + row_segment.header_ref_flag（史記目錄页题列）。"""
from types import SimpleNamespace

from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.row_segment import RowSegmentParams
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def test_defaults_off_and_not_in_dump():
    assert RowSegmentParams().header_ref_flag is False
    assert "header_ref_flag" not in RowSegmentParams().model_dump()
    assert SeedAdmitParams().lane_header_formula is False
    d = SeedAdmitParams().model_dump()
    assert "lane_header_formula" not in d and "lane_header_formula_re" not in d
    assert SeedAdmitParams(lane_header_formula=True).model_dump()["lane_header_formula"] is True


def _rec(i, char=None, admit=False, channel=None):
    return SimpleNamespace(id=f"01:87:3:{i}", char=char, admit=admit, channel=channel, provenance="",
                           doubts=["库 unsure"], evidence={})


def _run(monkeypatch, line, recs, col=3):
    cells = SimpleNamespace(columns=[SimpleNamespace(col=col, flags=[f"header_ref:{line}"])])
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: cells)
    out = [SimpleNamespace(col=col, chars=recs)]
    return sa._header_formula_pass(None, 87, SeedAdmitParams(lane_header_formula=True), out), recs


def test_admits_by_line_when_counts_match(monkeypatch):
    recs = [_rec(i, c) for i, c in zip(range(2, 7), "本𣏌當年三")]
    recs[0].admit = True
    n, recs = _run(monkeypatch, "本紀第十一", recs)
    assert n == 4
    assert "".join(r.char for r in recs) == "本紀第十一"
    assert all(r.admit and r.doubts == ["lane_header_formula"] for r in recs[1:])
    assert recs[1].evidence["lane"]["prev_char"] == "𣏌"


def test_skips_when_count_differs_or_human_or_not_formula(monkeypatch):
    n, recs = _run(monkeypatch, "本紀第十一", [_rec(i, "x") for i in range(2, 6)])
    assert n == 0 and not any(r.admit for r in recs)
    recs = [_rec(i, "x") for i in range(2, 7)]
    recs[2].channel = "human"
    n, recs = _run(monkeypatch, "本紀第十一", recs)
    assert n == 4 and not recs[2].admit
    n, recs = _run(monkeypatch, "孝景帝", [_rec(i, "x") for i in range(1, 4)])
    assert n == 0


def test_overrides_few_admitted_conflicts_but_skips_shifted_column(monkeypatch):
    # 个别已放行格与整理本不一致（近形放错）→ 改成整理本字，不计入「新放行」格数
    recs = [_rec(i, c, admit=True) for i, c in zip(range(1, 7), "史記卷四十二")]
    n, recs = _run(monkeypatch, "史記卷四十一", recs)
    assert n == 0 and recs[-1].char == "一" and recs[-1].evidence["lane"]["prev_char"] == "二"
    # 超过三分之一已放行格不一致＝整列错位 → 整列不动
    recs = [_rec(i, c, admit=True) for i, c in zip(range(1, 7), "史十卷記記一")]
    n, recs = _run(monkeypatch, "史記卷四十一", recs)
    assert n == 0 and "".join(r.char for r in recs) == "史十卷記記一"


def test_skips_column_with_frame_junk(monkeypatch):
    cells = SimpleNamespace(columns=[SimpleNamespace(col=3, flags=["header_ref:本紀第十一",
                                                                   "layout_frame_junk：列端 1 格的墨不像字"])])
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: cells)
    recs = [_rec(i, "x") for i in range(2, 7)]
    out = [SimpleNamespace(col=3, chars=recs)]
    assert sa._header_formula_pass(None, 87, SeedAdmitParams(lane_header_formula=True), out) == 0
