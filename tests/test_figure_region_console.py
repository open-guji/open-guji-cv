"""控制台插图块画框（GUJI-737 收尾）：列范围换算、按框算列号、校验、写 `figure_region` 并读回。

自造两页产物（只要 border_detect 尺寸与 cell_shrink 字框），全部落 tmp；直调端点函数，不起 TestClient。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from open_guji_cv.console.auth import Identity
from open_guji_cv.feedback import figures as F

_ID = Identity(email="fig-test@example.com", role="reviewer", tier="reviewer")
W, H = 1000, 1400


def _col(col: int, x_tr0: float, x_tr1: float, n: int = 3) -> dict:
    """cv 右上原点的一列：n 个字框，横向 [x_tr0, x_tr1]。"""
    return {"col": col, "chars": [{"id": f"volx:9:{col}:{i}", "cell_type": "char",
                                   "bbox_page": [x_tr0, 100 + 120 * i, x_tr1, 200 + 120 * i]} for i in range(1, n + 1)]}


class FakeStore:
    def __init__(self, pages: dict[int, list[dict]]):
        self.pages = pages

    def read_raw(self, book, step, key):
        pg = int(key[1:])
        if pg not in self.pages:
            return None
        if step == "border_detect":
            return {"borders": {"width": W, "height": H}}
        if step == "cell_shrink":
            return {"char_index": {"columns": self.pages[pg], "page": pg}}
        return None


# 右上原点：列 1 在最右（左上 x≈800..900），列 2、3、4 依次往左，每列宽 100、间隔 100
COLS = [_col(1, 99, 199), _col(2, 299, 399), _col(3, 499, 599), _col(4, 699, 799)]


def test_page_columns_converts_to_top_left():
    Wd, Hd, cols = F.page_columns(FakeStore({9: COLS}), "volx", 9)
    assert (Wd, Hd) == (W, H)
    assert [c["col"] for c in cols] == [1, 2, 3, 4]
    assert cols[0]["x"] == 800 and cols[0]["w"] == 100        # (W-1)-199 = 800 … (W-1)-99 = 900
    assert cols[3]["x"] == 200


def test_columns_for_box():
    _, _, cols = F.page_columns(FakeStore({9: COLS}), "volx", 9)
    assert F.columns_for_box(cols, [380, 100, 330, 900]) == (2, 2)     # 列 2、3 整盖，列 1 没碰
    assert F.columns_for_box(cols, [180, 100, 740, 900]) == (1, 4)     # 整页四列
    assert F.columns_for_box(cols, [0, 0, 100, 100]) is None           # 页边空白，一列没占
    with pytest.raises(ValueError):
        F.columns_for_box([{"col": 1, "x": 800, "w": 100}, {"col": 3, "x": 400, "w": 100}], [380, 0, 540, 100])


def test_normalize_regions_fills_col_and_rejects_bad():
    _, _, cols = F.page_columns(FakeStore({9: COLS}), "volx", 9)
    out = F.normalize_regions([{"box": [380.4, 90, 330, 1000.6], "alt": " 河圖 "}], cols, W, H)
    assert out == [{"box": [380, 90, 330, 1001], "col": 2, "span": 2, "alt": "河圖"}]
    # 框伸出页外：裁到页内
    assert F.normalize_regions([{"box": [-20, -5, 300, 2000], "col": 4, "span": 1}], cols, W, H)[0]["box"] == [0, 0, 280, H]
    # 手填列号、没给 span：按框算（列号对得上时）
    assert F.normalize_regions([{"box": [180, 100, 540, 900], "col": 3}], cols, W, H)[0]["span"] == 2
    with pytest.raises(ValueError, match="列号"):        # 空白处画框、没填列号
        F.normalize_regions([{"box": [0, 0, 150, 150]}], cols, W, H)
    with pytest.raises(ValueError, match="重叠"):
        F.normalize_regions([{"box": [600, 0, 300, 500]}, {"box": [780, 600, 150, 500]}], cols, W, H)
    with pytest.raises(ValueError, match="id"):
        F.normalize_regions([{"box": [600, 0, 300, 500], "fig": "Fig 1"}], cols, W, H)
    with pytest.raises(ValueError, match="60"):
        F.normalize_regions([{"box": [600, 0, 300, 500], "alt": "图" * 61}], cols, W, H)
    assert F.normalize_regions([], cols, W, H) == []


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from open_guji_cv.console import deps
    from open_guji_cv.console.routers import figure_region as router
    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)
    monkeypatch.setattr(deps, "product_store", lambda: FakeStore({9: COLS, 10: []}))
    return router


def test_save_then_read_back_and_overwrite(env):
    router = env
    assert router.api_figure_region_page("volx", 9)["regions"] == []
    r = router.api_figure_region_save("volx", 9, router.RegionsIn(regions=[{"box": [380, 90, 330, 1000], "alt": "河圖"}]),
                                      identity=_ID)
    assert r["appended"] == 1 and r["regions"] == [{"box": [380, 90, 330, 1000], "col": 2, "span": 2, "alt": "河圖"}]
    page = router.api_figure_region_page("volx", 9)
    assert page["width"] == W and [c["col"] for c in page["columns"]] == [1, 2, 3, 4]
    assert page["regions"][0]["alt"] == "河圖"
    # 导出读的就是这一份
    from open_guji_cv.console import deps
    assert F.resolved_figure_regions("volx", log=deps.event_log())[9][0]["col"] == 2
    # 再画一次整页覆盖；空表撤掉
    router.api_figure_region_save("volx", 9, router.RegionsIn(regions=[{"box": [780, 0, 150, 500], "alt": "卦"}]), identity=_ID)
    assert [x["col"] for x in router.api_figure_region_pages("volx")["pages"]["9"]] == [1]
    router.api_figure_region_save("volx", 9, router.RegionsIn(regions=[]), identity=_ID)
    assert router.api_figure_region_pages("volx")["pages"] == {}


def test_save_rejects_without_writing(env):
    router = env
    with pytest.raises(HTTPException) as e:                 # 第 10 页没有字框：不填列号算不出
        router.api_figure_region_save("volx", 10, router.RegionsIn(regions=[{"box": [100, 100, 500, 500]}]), identity=_ID)
    assert e.value.status_code == 400
    assert router.api_figure_region_pages("volx")["pages"] == {}
    ok = router.api_figure_region_save("volx", 10, router.RegionsIn(regions=[{"box": [100, 100, 500, 500], "col": 1, "span": 3}]),
                                       identity=_ID)
    assert ok["regions"][0]["span"] == 3
