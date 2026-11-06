# -*- coding: utf-8 -*-
"""`steps/row_segment_coltext.py`：自动配页的「逐列无格位」参照类型（page_map_ref: column_text）。数据全是自造的。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.steps import row_segment_coltext as CT
from open_guji_cv.steps.row_segment import RowSegmentParams

NS, NCOL = 22, 9
CHARS = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結為霜"


def _grid(cols: list[tuple[int, int]], thin: set[tuple[int, int]] = frozenset()) -> np.ndarray:
    """每列 (起格, 字数) → 格墨 (NCOL, NS)；`thin` 里的 (列, 格) 是量不出墨的细字（一、二）。"""
    g = np.full((NCOL, NS), 0.01, dtype=np.float32)
    for c, (st, n) in enumerate(cols):
        for k in range(st, st + n):
            if (c + 1, k) not in thin:
                g[c, k - 1] = 0.15
    return g


def _leaf_text(counts: list[int], seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    return ["".join(CHARS[int(i)] for i in rng.integers(0, len(CHARS), n)) for n in counts]


def _corpus(tmp_path, leaves: list[tuple[str, list[str]]]):
    p = tmp_path / "grid.txt"
    p.write_text("#@ header\n" + "".join(f"#@ {h}\n" + "".join(x + "\n" for x in ls) for h, ls in leaves),
                 encoding="utf-8")
    return p


def test_choose_picks_inked_run_and_tolerates_thin_chars():
    ink = np.zeros(NS)
    good = [3, 4, 6, 7, 8]          # 第 5 格是细字，量不出墨
    ink[[2, 3, 5, 6, 7]] = 0.2
    assert CT.choose(good, 6, ink, NS) == [3, 4, 5, 6, 7, 8]
    # 段外的墨紧贴着段：分不清是字还是框条，不出行
    assert CT.choose([3, 4, 5, 6], 3, ink, NS) is None
    # 满列：字数钉住段，缺墨格多一些也照出
    full = [k for k in range(1, NS + 1) if k % 3]
    assert CT.choose(full, NS, np.ones(NS), NS) == list(range(1, NS + 1))


def test_page_rows_pairs_columns_with_lines_and_marks_notes():
    from open_guji_cv.steps.align_ref_coord import parse_lines
    text = ["天地玄黃宇宙", "洪荒<日月|盈>昃", "辰宿"]
    lines = [[u for u in rl.units if u.kind != "b"] for rl in parse_lines("#@ x\n" + "\n".join(text))]
    g = _grid([(3, 6), (1, 5), (0, 0), (5, 2)] + [(0, 0)] * 5)
    rows = {r["col"]: r for r in CT.page_rows("001", 7, g, lines, NS, head="h1")}
    assert rows[1]["slots"] == [3, 4, 5, 6, 7, 8]
    assert rows[2]["slots"] == [1, 2, 3, 4, 5] and rows[2]["notes"] == [3] and rows[2]["half"] == [4]
    assert rows[3]["slots"] == [] and rows[9]["slots"] == []      # 没墨的列出空列
    assert rows[4]["slots"] == [5, 6]


def test_build_auto_aligns_pages_and_skips_pages_not_in_reference(tmp_path):
    rng = np.random.default_rng(3)
    halves = []
    for i in range(40):
        counts = [int(x) for x in rng.integers(4, NS + 1, NCOL)]
        if i % 5 == 0:
            counts = [NS] * NCOL           # 满页彼此分不开，靠前后次序定
        halves.append((f"KR_{i // 20 + 1:04d}-{i % 20 + 1:02d}a", counts))
    path = _corpus(tmp_path, [(h, _leaf_text(c, k)) for k, (h, c) in enumerate(halves)])
    # 册从第 6 个半叶起，中间夹一页参照没录的目录页（第 4 页），末页是封底
    seq = [None, None, None] + list(range(5, 12)) + ["toc"] + list(range(12, 30)) + [None]
    pages = list(range(1, len(seq) + 1))
    grids = []
    for h in seq:
        if h is None:
            grids.append(_grid([(0, 0)] * NCOL))
        elif h == "toc":
            grids.append(_grid([(2, 5)] * NCOL))
        else:
            grids.append(_grid([(1, n) for n in halves[h][1]]))
    d = CT.build("001", pages, grids, path, {}, "strict", NS, NCOL)
    got = {r["page"]: r["head"] for r in d["rows"]}
    for p, h in zip(pages, seq):
        if isinstance(h, int):
            assert got[p] == halves[h][0], p
    assert d["summary"]["bad_text_pages"] == []
    assert seq.index("toc") + 1 in d["summary"]["no_ref_pages"]
    assert d["summary"]["pages_with_layout"] == sum(isinstance(h, int) for h in seq)


def test_build_pins_mode_and_overrides(tmp_path):
    path = _corpus(tmp_path, [("A-01a", _leaf_text([5, 22], 1)), ("A-01b", _leaf_text([3], 2))])
    grids = [_grid([(1, 5), (1, 22)] + [(0, 0)] * 7), _grid([(2, 3)] + [(0, 0)] * 8)]
    d = CT.build("001", [1, 2], grids, path, {1: "A-01a", 2: "A-01b"}, "pins", NS, NCOL)
    lay = {(r["page"], r["col"]): r for r in d["layout"]}
    assert lay[1, 1]["slots"] == [1, 2, 3, 4, 5] and lay[2, 1]["slots"] == [2, 3, 4]
    rows = CT.apply_overrides(d["layout"], [{"vol": "001", "page": 2, "col": 1, "slots": [1, 2, 3], "why": "人核"},
                                            {"vol": "001", "page": 1, "col": 2, "drop": True}])
    lay = {(r["page"], r["col"]): r for r in rows}
    assert lay[2, 1]["slots"] == [1, 2, 3] and (1, 2) not in lay


def test_params_default_dump_unchanged():
    """缺省 column_slots 不进参数 dump（没开的书 params_hash 不变）；column_text 要给逐列文本。"""
    d = RowSegmentParams().model_dump()
    assert not any(k in d for k in ("page_map_ref", "page_map_ref_file", "page_map_overrides"))
    import pytest
    with pytest.raises(ValueError):
        RowSegmentParams(page_map="strict", page_map_ref="column_text")
