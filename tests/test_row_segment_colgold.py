"""Step3 逐列字数先验（doc/design/19 块 C）：按目标字数重切一次的决策与金标表读取。

只测纯逻辑：DP 用假函数代替（返回指定 kind 序列的「结果」），数据全部现造。
"""
import json
from types import SimpleNamespace

from open_guji_cv.steps.row_segment import RowSegmentParams, apply_count_target, load_colgold


def _res(kinds):
    return SimpleNamespace(cells=[SimpleNamespace(kind=k) for k in kinds])


def _seg_table(table):
    calls = []

    def seg(n):
        calls.append(n)
        return table.get(n)
    return seg, calls


def test_over_split_recut_accepted():
    # 切出 20 字，目标 19：格数 21→20 重切，重切出 19 字 → 采用
    r = _res(["blank"] + ["char"] * 20)
    seg, calls = _seg_table({20: _res(["blank"] + ["char"] * 19)})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert calls == [20] and n == 20 and r2 is not r
    assert flags and flags[0].startswith("colgold_prior")


def test_recut_still_wrong_keeps_original_and_flags():
    r = _res(["char"] * 20)
    seg, _ = _seg_table({20: _res(["char"] * 20)})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert r2 is r and n == 21 and flags[0].startswith("colgold_conflict")


def test_count_already_right_is_untouched():
    r = _res(["blank", "blank"] + ["char"] * 19)
    seg, calls = _seg_table({})
    r2, n, flags = apply_count_target(r, seg, 21, 19, "colgold")
    assert r2 is r and n == 21 and flags == [] and calls == []


def test_large_diff_not_applied():
    r = _res(["char"] * 21)
    seg, calls = _seg_table({})
    _, n, flags = apply_count_target(r, seg, 21, 15, "colgold")
    assert calls == [] and n == 21 and "超过" in flags[0]


def test_jiazhu_column_untouched():
    r = _res(["char"] * 10 + ["jiazhu_a", "jiazhu_b"] * 5)
    seg, calls = _seg_table({})
    r2, n, flags = apply_count_target(r, seg, 21, 12, "colgold")
    assert r2 is r and calls == [] and flags == []


def test_under_split_adds_slot():
    r = _res(["char"] * 18)
    seg, calls = _seg_table({22: _res(["char"] * 19)})
    _, n, flags = apply_count_target(r, seg, 21, 19, "yolo")
    assert calls == [22] and n == 22 and flags[0].startswith("yolo_prior")


def test_load_colgold_filters(tmp_path):
    rows = [
        {"vol": "volX", "page": 3, "col": 1, "agree": True, "dzg": {"n": 19, "start": 0, "note": None}},
        {"vol": "volX", "page": 3, "col": 2, "agree": False, "dzg": {"n": 19, "note": None}},
        {"vol": "volX", "page": 3, "col": 3, "agree": True, "dzg": {"n": 25, "note": {"start": 5, "r": 3, "l": 3}}},
        {"vol": "volY", "page": 3, "col": 1, "agree": True, "dzg": {"n": 19, "note": None}},
        {"vol": "volX", "page": 3, "col": 4, "agree": True, "dzg": {"n": 19, "start": None, "note": None}},
    ]
    p = tmp_path / "colgold.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = load_colgold(str(p), "volX")
    assert set(got) == {(3, 1)}


def test_params_off_by_default_no_fingerprint():
    p = RowSegmentParams(cut_judge="rule")
    assert p.colgold_prior == "" and p.colgold_fingerprint == ""


# ── 块 D：原生 YOLO 并格闸的成对判定 ──────────────────────────────

from open_guji_cv.steps.row_segment import yolo_merge_pairs  # noqa: E402


def _yolo_normal(n=20, h=100):
    # 一列正常字框（列外另放，作中位高的底）
    return [(500, i * 110, 600, i * 110 + h) for i in range(n)]


def test_split_char_inside_one_yolo_box_counts_pair():
    ink = [(10, 10, 90, 40), (10, 60, 90, 95), (10, 120, 90, 210)]   # 前两格是被切开的「三」
    yolo = _yolo_normal() + [(5, 5, 95, 100), (5, 115, 95, 215)]
    assert yolo_merge_pairs(ink, yolo) == 1


def test_double_height_yolo_box_ignored():
    ink = [(10, 10, 90, 95), (10, 105, 90, 195)]                     # 两个真字
    yolo = _yolo_normal() + [(5, 5, 95, 200)]                        # YOLO 把两字并成一个 2 倍高框
    assert yolo_merge_pairs(ink, yolo) == 0


def test_cell_used_once():
    ink = [(10, 10, 90, 30), (10, 40, 90, 60), (10, 70, 90, 95)]
    yolo = _yolo_normal() + [(5, 5, 95, 100)]                        # 三格都在一个框里 → 只记一对
    assert yolo_merge_pairs(ink, yolo) == 1


def test_blank_cells_and_no_yolo():
    assert yolo_merge_pairs([None, (0, 0, 1, 1)], _yolo_normal()) == 0
    assert yolo_merge_pairs([(0, 0, 1, 1), (0, 2, 1, 3)], []) == 0


def test_colgold_count_ignores_low_ink_cells_outside_gold_slots():
    from open_guji_cv.steps.row_segment import colgold_count
    g = {"start": 2, "n": 3}                      # 金标：字在 3、4、5 格
    cells = [SimpleNamespace(kind="char", slot=1, ink_ratio=0.02),    # 抬头位残墨 → 不算
             SimpleNamespace(kind="char", slot=3, ink_ratio=0.03),    # 金标字位上的瘦字「一」→ 算
             SimpleNamespace(kind="char", slot=4, ink_ratio=0.2),
             SimpleNamespace(kind="char", slot=5, ink_ratio=0.2),
             SimpleNamespace(kind="char", slot=6, ink_ratio=0.15)]    # 金标外但墨足 → 算（真多切）
    assert colgold_count(g)(cells) == 4


def test_colgold_path_follows_corpus_dir(tmp_path, monkeypatch):
    # corpus/… 走 corpus_path：工作区根的 corpus/ 在就读它；其他相对路径按工作区根
    from open_guji_cv.steps.row_segment import _colgold_path
    (tmp_path / "corpus" / "daizhige").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert _colgold_path("corpus/daizhige/colgold.jsonl") == tmp_path / "corpus" / "daizhige" / "colgold.jsonl"
    assert _colgold_path("models/yolo") == tmp_path / "models" / "yolo"
    assert _colgold_path(str(tmp_path / "x.jsonl")) == tmp_path / "x.jsonl"


def test_colgold_count_skips_end_cell_cut_off_by_blank():
    # vol03 p75 c3：金标 3–19 格 17 字，20 格空、21 格残墨 0.08 → 不算（原先算成 18，C 误并两字）
    from open_guji_cv.steps.row_segment import colgold_count
    g = {"start": 2, "n": 17}
    cells = ([SimpleNamespace(kind="blank", slot=s, ink_ratio=0.0) for s in (1, 2)]
             + [SimpleNamespace(kind="char", slot=s, ink_ratio=0.2) for s in range(3, 20)]
             + [SimpleNamespace(kind="blank", slot=20, ink_ratio=0.0),
                SimpleNamespace(kind="char", slot=21, ink_ratio=0.08)])
    assert colgold_count(g)(cells) == 17
    cells[-2] = SimpleNamespace(kind="char", slot=20, ink_ratio=0.2)   # 连着金标字段 → 真多切，都算
    assert colgold_count(g)(cells) == 19


def test_colgold_count_walks_cells_not_slot_numbers():
    # vol04 p14 c4：抬头位 -1 后面直接是 1 号格，没有 0 号格；-1 上的墨不能因「0 号格不在」被当成隔开
    from open_guji_cv.steps.row_segment import colgold_count
    g = {"start": 0, "n": 3}
    cells = ([SimpleNamespace(kind="char", slot=-1, ink_ratio=0.28)]
             + [SimpleNamespace(kind="char", slot=s, ink_ratio=0.2) for s in (1, 2, 3)])
    assert colgold_count(g)(cells) == 4


def test_colgold_count_with_image_skips_frame_bar_next_to_text():
    # vol06 p40 c9：上框线落在金标字段前一格、紧挨首字、墨也够——有列图时按连通体高度判它不是字
    import numpy as np
    from open_guji_cv.steps.row_segment import colgold_count
    img = np.full((400, 100), 255, np.uint8)
    img[30:42, 0:100] = 0                     # 1 号格：一条满宽横线（高 12，格高 100）
    for y in (100, 200, 300):
        img[y + 10:y + 90, 30:70] = 0         # 2–4 号格：整字
    cells = [SimpleNamespace(kind="char", slot=s, ink_ratio=0.12 if s == 1 else 0.3,
                             x0=0, x1=100, y0=(s - 1) * 100, y1=s * 100) for s in (1, 2, 3, 4)]
    g = {"start": 1, "n": 3}
    assert colgold_count(g)(cells) == 4            # 不给图：照旧按墨量算上
    assert colgold_count(g, img)(cells) == 3       # 给图：横线不算
    img[10:90, 30:70] = 0                          # 1 号格换成整字 → 算（真多切）
    assert colgold_count(g, img)(cells) == 4


def test_colgold_count_with_image_keeps_stacked_strokes():
    # vol04 p12 c7：D 并好的「三」落在金标字段前一格——三横各自都矮，合起来纵跨够长 → 算字
    import numpy as np
    from open_guji_cv.steps.row_segment import colgold_count
    img = np.full((300, 100), 255, np.uint8)
    for y in (15, 45, 75):
        img[y:y + 10, 20:80] = 0              # 1 号格：三横
    for y in (100, 200):
        img[y + 10:y + 90, 30:70] = 0
    cells = [SimpleNamespace(kind="char", slot=s, ink_ratio=0.15,
                             x0=0, x1=100, y0=(s - 1) * 100, y1=s * 100) for s in (1, 2, 3)]
    assert colgold_count({"start": 1, "n": 2}, img)(cells) == 3


def test_colgold_count_raised_start_includes_slot_minus_one():
    # vol04 p7 c2：金标 start -1（抬头字），n 22 → 字在 -1、1…21 格
    from open_guji_cv.steps.row_segment import colgold_count
    cells = ([SimpleNamespace(kind="char", slot=-1, ink_ratio=0.01)]
             + [SimpleNamespace(kind="char", slot=s, ink_ratio=0.2) for s in range(1, 22)])
    assert colgold_count({"start": -1, "n": 22})(cells) == 22
