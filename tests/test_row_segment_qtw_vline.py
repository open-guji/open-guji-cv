"""row_segment 两个书级参数（全唐文开 border_detect.vline_track 后的切字适配，CV2 2026-11-27）：
`frame_edge_near`（列端框线格贴框距离）、`layout_off_always`（无先验格网总出场）。缺省不进参数哈希。"""
from open_guji_cv.steps.row_segment import RowSegmentParams


def test_defaults_not_in_params_dump():
    d = RowSegmentParams().model_dump()
    assert "frame_edge_near" not in d
    assert "layout_off_always" not in d


def test_on_values_in_params_dump():
    d = RowSegmentParams(frame_edge_near=0.25, layout_off_always=True, layout_off_tol=1).model_dump()
    assert d["frame_edge_near"] == 0.25
    assert d["layout_off_always"] is True
    assert d["layout_off_tol"] == 1
