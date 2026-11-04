"""换图源坐标换算（datastore/source_xform）：自造页表，不连网。"""
import numpy as np
import pytest

from open_guji_cv.datastore import source_xform as X


def _table(H, old=(100, 200), new=(150, 300), rev=3):
    return {"pages": [
        {"seq": "0001", "page": 1, "w": new[0], "h": new[1],
         "from_rev": {"rev": rev, "sha256": "0" * 64, "w": old[0], "h": old[1], "H": np.asarray(H).tolist()}},
        {"seq": "0002", "page": 2, "w": 10, "h": 10},            # 不是换源出来的页
    ]}


def test_scale_shift_points_tl_and_tr():
    H = [[1.5, 0, 4], [0, 1.5, -2], [0, 0, 1]]
    x = X.page_xforms(_table(H))["0001"]
    assert np.allclose(x.points([(10, 20)]), [(19, 28)])
    # 右上原点：旧 x_tr=10 → 旧 x_tl=90 → 新 x_tl=139 → 新 x_tr=150-139=11
    assert np.allclose(x.points([(10, 20)], X.TR), [(11, 28)])


def test_box_and_xywh_under_perspective():
    H = np.array([[1.4, 0.02, 3], [-0.01, 1.4, 5], [1e-5, 0, 1]])
    x = X.by_page(_table(H))[1]
    q = x.box_quad(10, 10, 50, 80)
    b = x.box(10, 10, 50, 80)
    assert b[0] == pytest.approx(q[:, 0].min()) and b[3] == pytest.approx(q[:, 1].max())
    xw = x.xywh(10, 10, 40, 70)
    assert xw[2] == pytest.approx(b[2] - b[0]) and xw[3] == pytest.approx(b[3] - b[1])
    # 逆矩阵换回来
    back = np.c_[q, np.ones(4)] @ np.linalg.inv(H).T
    assert np.allclose(back[:, :2] / back[:, 2:], [(10, 10), (50, 10), (50, 80), (10, 80)])


def test_skip_pages_without_from_rev_and_rev_check():
    t = _table(np.eye(3))
    assert set(X.page_xforms(t)) == {"0001"}
    assert X.from_rev(t) == 3
    t["pages"][1]["from_rev"] = {"rev": 2, "w": 1, "h": 1, "H": np.eye(3).tolist()}
    with pytest.raises(ValueError):
        X.from_rev(t)


def test_bad_origin_and_shape():
    x = X.page_xforms(_table(np.eye(3)))["0001"]
    with pytest.raises(ValueError):
        x.points([(0, 0)], "bottom-left")
    t = _table(np.eye(3)); t["pages"][0]["from_rev"]["H"] = [[1, 0], [0, 1]]
    with pytest.raises(ValueError):
        X.page_xforms(t)
