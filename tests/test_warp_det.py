"""`seg.warp._warp_perspective_det`：与 cv2.warpPerspective 只在取整边上差 1 级（S9）。"""
from __future__ import annotations

import cv2
import numpy as np

from open_guji_cv.seg.warp import _warp_perspective_det


def test_det_warp_close_to_cv2():
    rng = np.random.default_rng(0)
    img = cv2.GaussianBlur((rng.random((300, 200)) * 255).astype(np.uint8), (5, 5), 0)
    src = np.float32([[10, 12], [180, 8], [190, 290], [5, 285]])
    dst = np.float32([[0, 0], [170, 0], [170, 280], [0, 280]])
    m = cv2.getPerspectiveTransform(src, dst)
    ref = cv2.warpPerspective(img, m, (171, 281), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    got = _warp_perspective_det(img, m, (171, 281))
    assert got.shape == ref.shape and got.dtype == np.uint8
    d = np.abs(got.astype(int) - ref.astype(int))
    assert d.max() <= 1
    assert (d > 0).mean() < 0.02


def test_det_warp_identity_exact():
    img = (np.arange(60 * 40) % 251).astype(np.uint8).reshape(60, 40)
    got = _warp_perspective_det(img, np.eye(3), (40, 60))
    assert np.array_equal(got, img)


def test_det_warp_default_on_keeps_explicit_hashes():
    """2026-11-18 det_warp／cut_judge unet_f64 转缺省：显式写过的书 dump 不变，写 false 的等于转缺省前的缺省 dump。"""
    from open_guji_cv.steps.column_warp import ColumnWarpParams
    from open_guji_cv.steps.row_segment import RowSegmentParams
    assert ColumnWarpParams().det_warp is True
    assert ColumnWarpParams().model_dump() == ColumnWarpParams(det_warp=True).model_dump()
    assert "det_warp" not in ColumnWarpParams(det_warp=False).model_dump()
    assert RowSegmentParams().cut_judge == "unet_f64"
    assert RowSegmentParams(cut_judge="rule").model_dump()["cut_judge"] == "rule"
