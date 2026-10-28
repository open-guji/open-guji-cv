"""GUJI-748 新图：列末字的底横不当下框（frame_band_inner）、夹注跨中缝部件整块归一侧（_jiazhu_sides）。"""
import numpy as np


def _col_with_shi(frame: bool) -> np.ndarray:
    """宽 60、高 200 的列图：「士」（竖连着底横）底横在 y=150–155，版框在 y=185–188（frame=False 时没画框）。"""
    img = np.full((200, 60), 255, np.uint8)
    img[100:106, 8:52] = 0      # 上横
    img[95:156, 28:33] = 0      # 竖，连到底横
    img[150:156, 14:46] = 0     # 底横
    if frame:
        img[185:189, :] = 0
    return img


def test_bottom_stroke_attached_to_char_is_not_frame():
    from open_guji_cv.clustering.extractor import frame_band_inner
    # 提示在 185、容差 40：旧行为把 150 的底横当下框，条带截在底横上方
    _top, bot = frame_band_inner(_col_with_shi(frame=False), bottom_hint=185.0, top_hint=0.0, hint_tol=40)
    assert bot > 156
    _top, bot = frame_band_inner(_col_with_shi(frame=True), bottom_hint=185.0, top_hint=0.0, hint_tol=40)
    assert 156 < bot <= 185


def test_jiazhu_sides_moves_overhanging_part_whole():
    from open_guji_cv.clustering.extractor import _jiazhu_sides
    pre = np.full((40, 60), 255, np.uint8)
    pre[5:15, 24:50] = 0        # 右行字的横：越过中缝 30 一截（6/26）
    pre[20:30, 5:20] = 0        # 左行字
    right = _jiazhu_sides(pre, 30)
    assert right[10, 24:50].all()           # 整块归右行
    assert not right[25, 5:20].any()


def test_jiazhu_sides_keeps_straight_cut_for_glued_pair():
    from open_guji_cv.clustering.extractor import _jiazhu_sides
    pre = np.full((40, 60), 255, np.uint8)
    pre[5:15, 10:50] = 0        # 两字粘连、两边各半：照中缝切
    right = _jiazhu_sides(pre, 30)
    assert right[10, 30:50].all() and not right[10, 10:30].any()
