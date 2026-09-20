# -*- coding: utf-8 -*-
"""Step2 → Step3 交接的准入闸护栏（`scripts/export_step3_input.py`）。

重点护的是**两条负结果**，别让后人重蹈：

1. `side_floor` 量的是**原始（未抹侧）**投影的最低墨——不能改成量清理后的图。
   带边界本来就是按"墨量接近 0"挑的，在清理后的图上量它必然小，那是循环
   论证：实测两条人判 `mixed` 的列在清理后只有 0.008/0.003，反而比一批
   `clean` 列（最高 0.088）还低。
2. `gold_admits` 必须把 `mixed` 和 `idk` 都挡下。`mixed` = 人裁"界行残墨和
   字身分不开"，`idk` = "没看清"——两者都不是"两可"，都不该推给 Step3 当
   干净输入。
3. `stamp_noise_density`（L2b，2026-09-11 新增）只解决四种已知 mixed 机制
   里的一种——能干净拦下印章类污染，但对夹注列/局部弯界行没有筛选力，
   两条测试都留着（一条钉死"印章类分得开"、一条钉死"另外两种分不开"），
   别让人以为调阈值能让它覆盖更多。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "export_step3_input", REPO / "scripts" / "export_step3_input.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# 2026-09-20：原先这里有个 `GOLD = ../open-guji-dataset/...`，下面五条用例
# 拿它量「clean 与 mixed 两组的 side_floor / stamp_noise 分得开分不开」。
# 那是**对金标数据的测量**，不是代码行为：
#
# - 金标一扩，分布就变（模块头记的「114 列复核后 clean 上到 0.0417、mixed
#   低到 0.0038，完全重叠」正是这么来的），于是其中一条只能长期挂 xfail；
# - 数据集不在就整条 skip，云端五条一条没跑过。
#
# 结论本身（两条负结果 + 印章类分得开）留在模块头与
# `doc/segmentation_v2_pipeline.md`，要复量就跑评测 `guji eval run`。
# 这里改为用**合成列图**钉判据的**机制**——机制是代码的，分布是数据的。


def test_gold_admits_rejects_mixed_and_idk_and_unlabelled():
    assert mod.gold_admits(None)[0] is False
    assert mod.gold_admits({"text_band": None, "pending_text_band": True})[0] is False
    assert mod.gold_admits({"text_band": {"human_left": 5}, "verdict": "mixed"})[0] is False
    assert mod.gold_admits(
        {"text_band": {"human_left": 5}, "verdict": "clean",
         "border_class": {"top": "clean", "bottom": "idk"}})[0] is False
    ok, why = mod.gold_admits(
        {"text_band": {"human_left": 5}, "verdict": "clean",
         "border_class": {"top": "clean", "bottom": "none"}})
    assert ok and why == ""


def test_side_floor_needs_a_zero_run_not_just_a_thin_rule():
    """`side_floor` 报的是"这一侧**有没有**墨量归零的地方"，不是"边上有多少墨"。

    两根贯穿的细界行照样让 `side_floor=0`（线和字身之间是空的），这正确——
    那种列 Step2 抹掉界行就干净了。真正要挡的是人判 `mixed` 那种形态：**整
    片外侧都糊着淡墨、从头到尾找不到零区**（实测 vol01/47 c2/c7 左侧一路
    0.04~0.09）。这条用例把两种形态摆在一起，钉死判据量的是哪一个。
    """
    rng = np.random.default_rng(0)

    def with_chars(col):
        for y in range(20, 380, 40):
            col[y:y + 25, 45:80] = 0
        return col

    ruled = with_chars(np.full((400, 120), 255, np.uint8))
    ruled[:, 2:8] = 0
    ruled[:, 112:118] = 0
    assert mod.side_floor(ruled) == 0.0, "细界行两侧仍有零区，不该被闸挡下"

    smeared = with_chars(np.full((400, 120), 255, np.uint8))
    for x in range(0, 32):                       # 整片外侧都糊着淡墨，无零区
        smeared[rng.choice(400, 24, replace=False), x] = 0
    assert mod.side_floor(smeared) > mod.SIDE_FLOOR_MAX


def test_side_floor_is_measured_on_the_raw_column_not_the_cleaned_one():
    """同一列，抹侧之后 `side_floor` 会塌下来——所以只能在原图上量。

    带边界本来就是按"墨量接近 0"挑的，在 `clean_column` 的输出上量它必然小：
    这是循环论证，实测两条人判 `mixed` 的列在清理后只有 0.008/0.003，比一批
    `clean` 列（最高 0.088）还低。要是有人把 `side_floor` 改成量清理后的图，
    这条会响。
    """
    from open_guji_cv.utils.column_projection import clean_column
    rng = np.random.default_rng(1)
    col = np.full((400, 120), 255, np.uint8)
    for y in range(20, 380, 40):
        col[y:y + 25, 45:80] = 0
    for x in range(0, 32):
        col[rng.choice(400, 24, replace=False), x] = 0
    raw = mod.side_floor(col)
    cleaned = mod.side_floor(clean_column(col)[0])
    assert raw > mod.SIDE_FLOOR_MAX >= cleaned, f"原图 {raw:.4f} / 清理后 {cleaned:.4f}"


# ── 判据的机制（合成列图，不碰金标）────────────────────────────────

def _clean_column_img(h: int = 400, w: int = 120) -> np.ndarray:
    """一列规规矩矩的正文：居中的字身，两侧留白。"""
    col = np.full((h, w), 255, np.uint8)
    for y in range(20, h - 20, 40):
        col[y:y + 25, 45:80] = 0
    return col


def test_stamp_noise_separates_scattered_blobs_from_plain_text():
    """`stamp_noise_density`（L2b，2026-09-11 新增）认的是**整列散布的中等
    面积孤立墨点**（背景印章那种），正文字身不该触发它。

    这条钉的是判据的机制。它在真金标上「能干净拦下印章类、对夹注列与局部
    弯界行没有筛选力」是**数据上的结论**，记在模块头与
    `column_projection.stamp_noise_density` 的文档字符串里，别指望调阈值能
    让它覆盖更多——那两种污染在「中等面积孤立墨点」这个维度上就是长得像
    正常笔画。
    """
    rng = np.random.default_rng(7)
    clean = _clean_column_img()
    stamped = _clean_column_img()
    # 墨块边长取 7（面积 49）：判据只数 `lo_area=3 ≤ 面积 ≤ hi_area=60` 的
    # 连通体——比这大的是字身笔画本体，比这小的是扫描灰尘，都不算。
    for _ in range(60):
        y, x = int(rng.integers(5, 385)), int(rng.integers(5, 105))
        stamped[y:y + 7, x:x + 7] = 0

    assert mod.stamp_noise_density(stamped) > mod.stamp_noise_density(clean), (
        f"印章列 {mod.stamp_noise_density(stamped):.4f} 不高于干净列 "
        f"{mod.stamp_noise_density(clean):.4f}")


def test_side_floor_cannot_see_contamination_away_from_the_edges():
    """记录 `side_floor` 结构性看不见的那一类污染，别再拿它当全能判据。

    它只量两侧外 25% —— 污染要是不贴边（弯界行只在列中段探入、背景印章
    整列散布噪点）就测不到。这不是参数没调好，是这条尺子的设计范围本来
    就只覆盖「贴边」这一种形态。**扩大金标不会把它挽救回来**，需要的是另
    一条独立于「两侧墨量」的判据（整列噪点密度 / 连通域特征）。

    合成：同样一列，污染分别摆在**边上**和**中段**，前者报得出、后者报不出。
    """
    rng = np.random.default_rng(3)
    at_edge = _clean_column_img()
    for x in range(0, 30):                    # 贴边：整片外侧糊着淡墨，无零区
        at_edge[rng.choice(400, 24, replace=False), x] = 0
    in_middle = _clean_column_img()
    for x in range(40, 70):                   # 同样的量，摆到列中段
        in_middle[rng.choice(400, 24, replace=False), x] = 0

    assert mod.side_floor(at_edge) > mod.SIDE_FLOOR_MAX, "贴边污染该报得出"
    assert mod.side_floor(in_middle) <= mod.SIDE_FLOOR_MAX, (
        "如果这条开始失败，说明 side_floor 意外能看见中段污染了——"
        "先去查它的窗口口径是不是被改宽了，而不是庆祝判据修好了")


def _fake_step2_columns(root: Path, page: int, cols: list[np.ndarray]) -> Path:
    """造一份 Step2 列图产物（`<page>/windows.json` + 列图），供 `main()` 吃。"""
    import cv2

    d = root / str(page)
    d.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, img in enumerate(cols, start=1):
        name = f"c{i:02d}.png"
        cv2.imwrite(str(d / name), img)
        h, w = img.shape
        entries.append({"col": i, "file": name,
                        "warped_size": {"width": w, "height": h},
                        "border_top_in_column": 0.0,
                        "border_bottom_in_column": float(h),
                        "raised": False, "head_raise_inner_y": None})
    (d / "windows.json").write_text(json.dumps({"columns": entries}),
                                    encoding="utf-8")
    return d


def test_stamp_noise_flags_columns_without_blocking_them(tmp_path, monkeypatch):
    """端到端钉死 flag 语义：命中 L2b（背景印章）的列 **flag 但不拦**——
    `admitted` 只由页级 / L2 两条 block 判据决定。

    直接跑 `main()`，不重新拼一遍判定逻辑，免得测试与实现各自维护一份
    「如果 stamp 超标该怎样」的认知、改了一边忘了另一边。

    2026-09-20 改：原先吃的是仓里 `output/vol02/step2_columns/3/` 那份跑批
    产物，产物不在就 skip。现在整页列图由测试自己合成——九列，每列都撒上
    印章噪点，但两侧留白干净（不触发 L2）。
    """
    import sys

    rng = np.random.default_rng(11)
    cols = []
    for _ in range(mod.EXPECTED_COLS):
        img = _clean_column_img()
        for _ in range(60):
            y, x = int(rng.integers(5, 385)), int(rng.integers(35, 85))
            img[y:y + 7, x:x + 7] = 0
        cols.append(img)
    src = _fake_step2_columns(tmp_path / "step2_columns", 3, cols).parent
    # 脚本把 `--src` 记成相对仓根的路径（`src.relative_to(ROOT)`），
    # 所以这里把它认的仓根也挪到 tmp 下。
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    argv = sys.argv
    sys.argv = ["export_step3_input.py", "--book", "tbook", "--src", str(src),
                "-o", str(tmp_path / "step3_input"), "--tier", "gate"]
    try:
        mod.main()
    finally:
        sys.argv = argv

    manifest = json.loads(
        (tmp_path / "step3_input" / "manifest.json").read_text(encoding="utf-8"))
    page3 = next(p for p in manifest["pages"] if p["page"] == "3")
    flagged = [c for c in page3["columns"] if c["flags"]]
    assert len(flagged) == mod.EXPECTED_COLS, \
        f"全页 {mod.EXPECTED_COLS} 列都该被 L2b 标记，实际 {len(flagged)}"
    assert all("L2b" in f for c in flagged for f in c["flags"])
    flagged_only = [c for c in flagged if not c["reject"]]
    assert flagged_only, "该有几列只踩 L2b、没踩 block 级判据，用来验证 flag 不拦截"
    assert all(c["admitted"] for c in flagged_only), (
        "L2b 命中不该单独拦截——只踩 L2b 的列应该仍然 admitted=True、正常推给 Step3")
