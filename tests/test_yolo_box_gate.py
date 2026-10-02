"""Step4 收框复核闸（Y1，overview#373）：判据、弃权、关着时参数哈希不变。全部自造数据，不碰 onnx 模型。"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.core.engine import params_hash
from open_guji_cv.steps import cell_shrink as cs
from open_guji_cv.steps.seed_admit import SeedAdmitParams
from open_guji_cv.utils import yolo_boxes as yb


def _ink(h=300, w=120):
    return np.zeros((h, w), np.uint8)


def test_extra_ink_agree_is_zero():
    ink = _ink()
    ink[110:190, 30:90] = 1
    box = (30.0, 110.0, 90.0, 190.0)
    assert yb.extra_ink_ratio(ink, box, box, (100.0, 200.0)) == 0.0


def test_extra_ink_cv_only_top_stroke():
    """CV 只框到最上一笔（20 行），YOLO 框整字（80 行）：多出的墨占大头。"""
    ink = _ink()
    ink[110:190, 40:80] = 1
    cv = (40.0, 110.0, 80.0, 130.0)
    yolo = (40.0, 110.0, 80.0, 190.0)
    assert yb.extra_ink_ratio(ink, cv, yolo, (100.0, 200.0)) == pytest.approx(0.75)


def test_extra_ink_ignores_neighbour_cell():
    """YOLO 框探进邻格的笔画不算：只数本格格线 ±PAD 内的墨。"""
    ink = _ink()
    ink[110:190, 40:80] = 1
    ink[200:260, 40:80] = 1                       # 下一格的字
    cv = (40.0, 110.0, 80.0, 190.0)
    yolo = (40.0, 110.0, 80.0, 260.0)
    assert yb.extra_ink_ratio(ink, cv, yolo, (100.0, 200.0)) < 0.1


def test_extra_ink_yolo_smaller_not_flagged():
    ink = _ink()
    ink[110:190, 40:80] = 1
    cv = (40.0, 110.0, 80.0, 190.0)
    yolo = (40.0, 130.0, 80.0, 170.0)
    assert yb.extra_ink_ratio(ink, cv, yolo, (100.0, 200.0)) == 0.0


def test_match_yolo_abstains_outside_cell():
    boxes = [(40.0, 210.0, 80.0, 290.0)]          # 中心 y=250，在别的格
    assert yb.match_yolo((40.0, 110.0, 80.0, 190.0), (100.0, 200.0), boxes) is None
    assert yb.match_yolo((40.0, 110.0, 80.0, 190.0), (100.0, 200.0),
                         [(40.0, 120.0, 80.0, 180.0)]) == (40.0, 120.0, 80.0, 180.0)


def test_nms_keeps_best_overlapping():
    xywh = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [50, 50, 10, 10]], float)
    assert sorted(yb._nms(xywh, np.array([0.5, 0.9, 0.4]), 0.45)) == [1, 2]


def test_missing_weights_abstain(tmp_path):
    with pytest.raises(yb.YoloUnavailable):
        yb.detect(str(tmp_path / "nope.onnx"), np.zeros((50, 50), np.uint8))
    p = cs.CellShrinkParams(yolo_gate=True, yolo_weights=str(tmp_path / "nope.onnx"))
    assert cs._yolo_weights(p, {}) is None        # 缺权重 = 弃权，不报错
    assert cs._yolo_weights(cs.CellShrinkParams(), {}) is None


def test_seal_page_abstains(tmp_path):
    (tmp_path / "slide").mkdir(); (tmp_path / "type").mkdir()
    w = tmp_path / "slide" / "best.onnx"; w.write_bytes(b"x")
    (tmp_path / "type" / "best.onnx").write_bytes(b"y")
    p = cs.CellShrinkParams(yolo_gate=True, yolo_weights=str(w), yolo_max_seal=2)
    assert cs._yolo_weights(p, {}) == (str(w), str(tmp_path / "type" / "best.onnx"))
    assert cs._yolo_weights(p, {(1, 1, ""): 1, (1, 2, ""): 1}) is not None
    assert cs._yolo_weights(p, {(1, i, ""): 1 for i in range(3)}) is None


def test_weights_fingerprint_is_content_not_path(tmp_path):
    a, b, c = tmp_path / "a.onnx", tmp_path / "sub_b.onnx", tmp_path / "c.onnx"
    a.write_bytes(b"model-1"); b.write_bytes(b"model-1"); c.write_bytes(b"model-2")
    assert yb.weights_fingerprint(str(a)) == yb.weights_fingerprint(str(b)) != yb.weights_fingerprint(str(c))
    assert yb.weights_fingerprint(str(tmp_path / "missing")) == ""


def test_match_with_x_range():
    boxes = [(40.0, 120.0, 80.0, 180.0), (240.0, 120.0, 280.0, 180.0)]
    assert yb.match_yolo((40.0, 110.0, 80.0, 190.0), (100.0, 200.0), boxes, (20.0, 100.0)) == boxes[0]
    assert yb.match_yolo((40.0, 110.0, 80.0, 190.0), (100.0, 200.0), boxes, (200.0, 300.0)) is None


def test_params_off_leave_hash_untouched():
    """闸关着：yolo_* 不进 dump、参数哈希与加字段前相同（产物逐字节不变的前提）。"""
    d = cs.CellShrinkParams().model_dump(mode="json")
    assert not [k for k in d if k.startswith("yolo")]
    assert set(d) == {"strategy", "padding_ratio", "min_ink_ratio", "seal_flag", "frame_guard"}
    assert params_hash(cs.CellShrinkParams(yolo_extra_ink=0.9)) == params_hash(cs.CellShrinkParams())
    d2 = SeedAdmitParams(db_path="x").model_dump(mode="json")
    assert "yolo_box_review" not in d2
    assert "yolo_box_review" in SeedAdmitParams(db_path="x", yolo_box_review=True).model_dump(mode="json")


def test_params_on_path_not_in_fingerprint_content_is():
    spec_paths = cs.CellShrinkStep.spec.path_params
    a = cs.CellShrinkParams(yolo_gate=True, yolo_weights="/a/x.onnx", yolo_weights_fp="f1")
    b = cs.CellShrinkParams(yolo_gate=True, yolo_weights="/b/y.onnx", yolo_weights_fp="f1")
    c = cs.CellShrinkParams(yolo_gate=True, yolo_weights="/a/x.onnx", yolo_weights_fp="f2")
    assert params_hash(a, path=spec_paths) == params_hash(b, path=spec_paths)
    assert params_hash(a, path=spec_paths) != params_hash(c, path=spec_paths)
    assert params_hash(a, path=spec_paths) != params_hash(cs.CellShrinkParams(), path=spec_paths)


def test_edge_side_skip():
    """列末格 CV 框贴着字、YOLO 框把下版框碎墨也包进来：不跳过会误报，skip_bottom 后为 0；
    反方向（版框线在 CV 框里、字在上方）skip_bottom 不影响。"""
    ink = _ink(h=320)
    ink[110:190, 40:80] = 1
    ink[192:205, 20:100] = 1                           # 下版框碎墨
    cv, yolo = (40.0, 110.0, 80.0, 190.0), (20.0, 108.0, 100.0, 206.0)
    cell = (100.0, 215.0)
    assert yb.extra_ink_ratio(ink, cv, yolo, cell) > 0.2
    assert yb.extra_ink_ratio(ink, cv, yolo, cell, skip_bottom=True) == 0.0
    # 版框线被当末字：CV 框只有那条线（y 195~205），字在上方
    cv2 = (20.0, 192.0, 100.0, 205.0)
    yolo2 = (40.0, 110.0, 80.0, 190.0)
    assert yb.extra_ink_ratio(ink, cv2, yolo2, (100.0, 215.0), skip_bottom=True) > 0.25
    # 列首格：上侧版框碎墨同理
    ink2 = _ink(h=320)
    ink2[100:108, 20:100] = 1
    ink2[110:190, 40:80] = 1
    assert yb.extra_ink_ratio(ink2, (40.0, 110.0, 80.0, 190.0), (20.0, 98.0, 100.0, 190.0), (90.0, 200.0)) > 0.1
    assert yb.extra_ink_ratio(ink2, (40.0, 110.0, 80.0, 190.0), (20.0, 98.0, 100.0, 190.0), (90.0, 200.0),
                              skip_top=True) == 0.0


def test_seed_admit_yolo_box_review_gate():
    from types import SimpleNamespace
    from open_guji_cv.steps.seed_admit import _yolo_box_review
    im = SimpleNamespace(flags=["yolo_box"])
    on, off = SeedAdmitParams(db_path="x", yolo_box_review=True), SeedAdmitParams(db_path="x")
    assert _yolo_box_review(on, im) and not _yolo_box_review(off, im)
    assert not _yolo_box_review(on, SimpleNamespace(flags=["seal_region"]))
    assert not _yolo_box_review(on, None)               # 没有 char_index = 弃权
