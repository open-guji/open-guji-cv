"""extractor.py 单测：合成 grid JSON + 合成页面 → 提取正确性。"""

import numpy as np

from open_guji_cv.clustering.extractor import CharExtractor


def _make_page_and_grid():
    """构造 200×300 白底页面：2 列 × 每列 3 个字块（暗色矩形）。"""
    page = np.full((300, 200), 235, dtype=np.uint8)
    columns = []
    # 列 1（右侧）x∈[120,180]，列 2（左侧）x∈[20,80]
    for col_no, (lx, rx) in [(1, (120.0, 180.0)), (2, (20.0, 80.0))]:
        cells = [{"type": "margin", "y_top": 0.0, "y_bottom": 10.0}]
        y = 10.0
        for idx in range(3):
            y_top, y_bottom = y, y + 60.0
            page[int(y_top) + 8:int(y_bottom) - 8,
                 int(lx) + 8:int(rx) - 8] = 30   # 墨块
            cells.append({"type": "char", "index": idx,
                          "y_top": y_top, "y_bottom": y_bottom,
                          "text": "字", "confidence": 0.9})
            y = y_bottom + 5.0
        cells.append({"type": "empty", "index": 3,
                      "y_top": y, "y_bottom": y + 60.0,
                      "text": None, "confidence": 0.0})
        columns.append({"index": col_no, "left_x": lx, "right_x": rx,
                        "cells": cells})
    grid = {"columns": columns}
    return page, grid


def test_extract_counts_and_ids():
    page, grid = _make_page_and_grid()
    results = CharExtractor().extract_page(page, grid, "bookX", "5")
    assert len(results) == 6  # 2 列 × 3 char（empty/margin 不提取）
    ids = [inst.id for inst, _ in results]
    assert len(set(ids)) == 6
    assert "bookX:5:1:0" in ids
    assert "bookX:5:2:2" in ids


def test_patch_is_the_tight_ink_box():
    """裁剪策略定版（2026-08-24）：图块 = 本字墨迹外接框 ±TIGHT_MARGIN。

    旧断言写的是「垂直外扩、水平内缩」——那是从墙裁到墙的年代。现在
    bbox 就是紧框，height/width 由它算出，两者必须逐像素相等；贴墙的
    空白装的从来不是字，多留一列都是回归。
    """
    from open_guji_cv.clustering.extractor import (BINARY_THRESHOLD_PATCH,
                                                   TIGHT_MARGIN)
    page, grid = _make_page_and_grid()
    extractor = CharExtractor(padding_ratio=0.1)
    seen = 0
    for inst, patch in extractor.extract_page(page, grid, "b", "1"):
        x0, y0, x1, y1 = inst.bbox
        assert 0 <= x0 < x1 <= page.shape[1]
        assert 0 <= y0 < y1 <= page.shape[0]
        assert (y1 - y0) == inst.height and (x1 - x0) == inst.width
        assert patch.shape == (int(round(y1)) - int(round(y0)),
                               int(round(x1)) - int(round(x0)))
        ys, xs = np.nonzero(patch < BINARY_THRESHOLD_PATCH)
        if ys.size == 0:                      # 判空格没有墨可量
            continue
        seen += 1
        assert ys.min() <= TIGHT_MARGIN and xs.min() <= TIGHT_MARGIN
        assert patch.shape[0] - 1 - ys.max() <= TIGHT_MARGIN
        assert patch.shape[1] - 1 - xs.max() <= TIGHT_MARGIN
    assert seen > 0


def test_ink_ratio_and_flags():
    page, grid = _make_page_and_grid()
    # 把列 1 第 0 个字块清空 → 应标 suspect_empty
    page[18:62, 128:172] = 235
    results = CharExtractor().extract_page(page, grid, "b", "1")
    by_id = {inst.id: inst for inst, _ in results}
    assert "suspect_empty" in by_id["b:1:1:0"].flags
    assert by_id["b:1:1:1"].ink_ratio > 0.2
    assert not by_id["b:1:1:1"].flags


def test_instance_json_roundtrip():
    from open_guji_cv.clustering.extractor import CharInstance
    page, grid = _make_page_and_grid()
    inst, _ = CharExtractor().extract_page(page, grid, "b", "1")[0]
    restored = CharInstance.from_json(inst.to_json())
    assert restored == inst


def test_edge_blob_spares_a_detached_part_of_the_character():
    """「冬」的下两点整体落在底部带内、但贴着主体——那是本字，不是残余。

    格线吸附收紧图块后这类部件常顶到边缘带；没有间隙条件时它被误判，
    确定层的零误报因此失守（实测 vol01/10:2:6）。
    """
    import numpy as np
    from open_guji_cv.clustering.extractor import _defect_features
    g = np.full((140, 150), 255, np.uint8)
    g[20:110, 20:130] = 0                 # 主体
    g[114:132, 60:90] = 0                 # 分离部件：距主体 4px（0.03h），在底部带内
    assert _defect_features(g)["edge_blob"] == 0.0


def test_edge_blob_still_fires_on_a_far_neighbor_residue():
    """真残余隔着整条字间空白（实测 +0.206×图块高），必须仍然报。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import _defect_features
    g = np.full((140, 150), 255, np.uint8)
    g[40:105, 20:130] = 0                 # 主体
    g[2:18, 40:110] = 0                   # 顶部残余：距主体 22px（0.16h）
    assert _defect_features(g)["edge_blob"] > 0.03


def _jiazhu_patch(w=120, h=110):
    """两列并排的小字块：合起来占满列宽，中缝 6px。"""
    import numpy as np
    g = np.full((h, w), 255, np.uint8)
    g[20:90, 8:55] = 0          # 左子列
    g[15:85, 61:112] = 0        # 右子列
    return g


def test_jiazhu_gap_center_fires_on_side_by_side_small_chars():
    from open_guji_cv.clustering.extractor import _jiazhu_gap_center
    got = _jiazhu_gap_center(_jiazhu_patch())
    assert got is not None
    c, strength = got
    assert 50 < c < 66, c
    assert strength >= 500  # 实心矩形＝大连通体


def test_jiazhu_gap_center_spares_a_normal_radical_char():
    """左右结构字（部/郎）：单字只占 ~0.7 列宽，span 条件挡住。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import _jiazhu_gap_center
    g = np.full((110, 120), 255, np.uint8)
    g[10:100, 25:55] = 0        # 左部首
    g[10:100, 58:85] = 0        # 右部首（总跨度 0.5w）
    assert _jiazhu_gap_center(g) is None


def _e(c, s=2000.0):
    return None if c is None else (c, s)


def test_flag_jiazhu_runs_requires_consecutive_aligned_cells():
    from open_guji_cv.clustering.extractor import flag_jiazhu_runs
    # 连续三格缝对齐 → 全标；孤立一格 → 不标；缝错开 → 不标
    assert set(flag_jiazhu_runs([(0, _e(60.0)), (1, _e(62.0)),
                                 (2, _e(58.0))])) == {0, 1, 2}
    assert flag_jiazhu_runs([(0, _e(60.0)), (2, _e(60.0))]) == {}
    assert flag_jiazhu_runs([(0, _e(60.0)), (1, _e(90.0))]) == {}


def test_flag_jiazhu_runs_bridges_single_gap_cell():
    from open_guji_cv.clustering.extractor import flag_jiazhu_runs
    # vol02/5 col2 形态：idx17 单格判据落空（单侧墨太少）但两侧对齐
    # → 桥接进段，中心取邻格均值；两个连续 None 不桥（防扩散）
    got = flag_jiazhu_runs([(15, None), (16, _e(90.0)), (17, None),
                            (18, _e(94.0)), (19, _e(92.0)),
                            (20, _e(93.0))])
    assert set(got) == {16, 17, 18, 19, 20}
    assert got[17] == 92.0
    assert flag_jiazhu_runs([(0, _e(60.0)), (1, None), (2, None),
                             (3, _e(61.0))]) == {}


def test_flag_jiazhu_runs_vetoes_speckle_run():
    from open_guji_cv.clustering.extractor import flag_jiazhu_runs
    # vol01/3 col2：纸面碎点连成长段但无大连通体 → 段中位 strength
    # 低于 JIAZHU_CC_MIN，整段否决；个别薄字（一/三）strength 低不碍事
    assert flag_jiazhu_runs([(i, _e(60.0, 250.0))
                             for i in range(7)]) == {}
    mixed = [(0, _e(60.0)), (1, _e(61.0, 300.0)), (2, _e(60.0))]
    assert set(flag_jiazhu_runs(mixed)) == {0, 1, 2}


def test_jiazhu_reading_order_a_before_b_per_run():
    from open_guji_cv.clustering.extractor import (CharInstance,
                                                   jiazhu_reading_order)

    def inst(idx, sub=None):
        sid = f"b:1:1:{idx}{sub or ''}"
        return CharInstance(id=sid, book="b", page="1", col=1, idx=idx,
                            bbox=(0, 0, 1, 1), cell_type="char",
                            ocr_text=None, ocr_confidence=0.0,
                            patch_path="x.png", ink_ratio=0.1,
                            height=1.0, width=1.0, flags=[], sub=sub)

    # 正文 0,1 → 夹注段 2,3（先 a 全部再 b 全部）→ 正文 4
    col = [inst(0), inst(1), inst(2, "a"), inst(2, "b"),
           inst(3, "a"), inst(3, "b"), inst(4)]
    got = [r.id for r in jiazhu_reading_order(col[::-1])]  # 乱序输入
    assert got == ["b:1:1:0", "b:1:1:1", "b:1:1:2a", "b:1:1:3a",
                   "b:1:1:2b", "b:1:1:3b", "b:1:1:4"]


def test_strip_side_rule_cuts_only_outside_the_text_band():
    """界行竖条剥掉，文字带内的竖笔（忄/阝/川 的边竖）一根不许动。"""
    from open_guji_cv.clustering.extractor import strip_side_rule

    patch = np.full((100, 100), 235, dtype=np.uint8)
    patch[10:90, 42:92] = 30          # 字身
    patch[5:95, 2:7] = 30             # 界行竖条：贴左缘，离字身 25px
    patch[15:85, 32:36] = 30          # 带内竖笔：与字身分离但在带内
    # 图块左缘在整页上的 x=100；文字带 [130, 195]
    out = strip_side_rule(patch, 100.0, 130.0, 195.0)
    assert (out[5:95, 2:7] == 255).all(), "界行竖条没剥掉"
    assert (out[15:85, 32:36] == 30).all(), "带内竖笔被误剥（红线）"
    assert (out[10:90, 42:92] == 30).all(), "字身被动了"


def test_widen_wide_gutters_only_touches_the_anomalous_gap():
    """异常宽的列缝补到空白段中心，正常缝一动不动。"""
    from open_guji_cv.clustering.grid_segment import _widen_wide_gutters

    binary = np.zeros((200, 500), dtype=np.uint8)
    for lo, hi in [(10, 90), (110, 190), (210, 290), (350, 430)]:
        binary[20:180, lo:hi] = 1
    out = [(10.0, 95.0), (105.0, 195.0), (205.0, 295.0), (345.0, 435.0)]
    bands = [None, None, None, None]
    spans = [(0, 100), (100, 200)]
    _widen_wide_gutters(binary, spans, out, bands)
    assert out[0] == (10.0, 95.0), "正常缝被动了"
    assert out[1] == (105.0, 195.0), "正常缝被动了"
    # 295~345 这条 50px 的缝（正常缝 10px）：空白段 295~345，中心 320
    assert out[2][1] == out[3][0] == 320.0
    assert bands[2] is not None and bands[3] is not None


def test_strip_side_rule_spares_a_char_written_outside_the_band():
    """带外也住着字（职名的「臣」、夹注的左子列）：它的外沿竖笔不许剥。"""
    from open_guji_cv.clustering.extractor import strip_side_rule

    patch = np.full((100, 120), 235, dtype=np.uint8)
    patch[10:90, 46:76] = 30          # 带内的字身（右缘越出文字带一点）
    patch[15:85, 18:40] = 30          # 带外的小字（夹注左子列/职名的臣）
    patch[15:85, 8:14] = 30           # 那个小字的外沿竖笔：紧挨着它（4px）
    patch[5:95, 110:114] = 30         # 真界行：带外，离字身 34px
    # 图块左缘 x=0；文字带 [42, 74]
    out = strip_side_rule(patch, 0.0, 42.0, 74.0)
    assert (out[15:85, 8:14] == 30).all(), "带外小字的竖笔被剥了（红线）"
    assert (out[5:95, 110:114] == 255).all(), "真界行没剥掉"
    assert (out[10:90, 46:76] == 30).all(), "字身被动了"


def test_frame_band_inner_stops_at_the_bar_not_at_a_dense_text_row():
    """框带内缘只吃框线行；末行字再密也不算框带（红线：绝不吞字）。"""
    from open_guji_cv.clustering.extractor import frame_band_inner

    h, w = 600, 400
    page = np.full((h, w), 235, dtype=np.uint8)
    page[8:12, :] = 30                     # 上框：满宽横条
    page[560:566, :] = 30                  # 下框：满宽横条
    # 末行字：行墨率不低（每 8px 一竖，约 0.35），但没有长连续段
    page[500:556, ::8] = 30
    top, bot = frame_band_inner(page)
    assert top == 12, f"上框内缘 {top}"
    assert bot == 560, f"下框内缘 {bot}（吃进末行字了）"


def test_frame_band_clamp_keeps_the_tail_char_and_drops_the_bar():
    """列尾格：框线不进条带，字一个像素不少。"""
    from open_guji_cv.clustering.extractor import (BINARY_THRESHOLD_PATCH,
                                                   CharExtractor)
    h, w = 400, 200
    page = np.full((h, w), 235, dtype=np.uint8)
    page[6:10, :] = 30                              # 上框
    cells, y = [{"type": "margin", "y_top": 0.0, "y_bottom": 10.0}], 10.0
    for idx in range(3):
        y0, y1 = y, y + 110.0
        page[int(y0) + 20:int(y1) - 20, 70:130] = 30    # 每格一个墨块
        cells.append({"type": "char", "index": idx,
                      "y_top": y0, "y_bottom": y1})
        y = y1
    page[336:344, :] = 30                           # 下框：压在末格下沿之内
    grid = {"image_size": {"width": w, "height": h},
            "columns": [{"index": 1, "left_x": 60.0, "right_x": 140.0,
                         "cell_left_x": 55.0, "cell_right_x": 145.0,
                         "layout": "rigid", "cells": cells}],
            "grid": {"cell_h": 110.0, "period": 100.0}}
    got = {i.idx: p for i, p in CharExtractor().extract_page(page, grid, "b", "1")}
    tail = got[2]
    ink_rows = np.flatnonzero((tail < BINARY_THRESHOLD_PATCH).any(axis=1))
    assert ink_rows.size, "末格全空了"
    # 末格的墨块高 70px（y 250~320）：框线一行都不许进来
    assert int(ink_rows.max() - ink_rows.min()) + 1 <= 74, "下框线混进末格"
