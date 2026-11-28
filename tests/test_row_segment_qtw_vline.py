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


def test_jiazhu_edge_trim_dump_and_signature():
    """`jiazhu_edge_trim`（CV2 11-28，053 75:3）：缺省不进 dump；缺省实现 segment_column 认这个参数。"""
    import inspect
    from open_guji_cv.impl.keben import row_boundaries as RB
    assert "jiazhu_edge_trim" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(jiazhu_edge_trim=0.15).model_dump()["jiazhu_edge_trim"] == 0.15
    assert "jiazhu_edge_trim" in inspect.signature(RB.segment_column).parameters


def test_gap_center_recovers_after_edge_trim():
    """上一字的整宽字脚压在本格顶上时量不出中缝，去掉顶上一截就量得出（jiazhu_edge_trim 的前提）。"""
    import numpy as np
    from open_guji_cv.impl.keben import jiazhu_split
    patch = np.full((220, 340), 255, np.uint8)
    patch[60:200, 20:150] = 0          # 左行小字
    patch[60:200, 190:320] = 0         # 右行小字
    patch[0:25, 20:320] = 0            # 上一字伸进来的整宽字脚
    assert jiazhu_split.gap_center(patch, 340.0) is None
    assert jiazhu_split.gap_center(patch[30:190], 340.0) is not None
