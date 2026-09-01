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

GOLD = REPO.parent / "open-guji-dataset" / "char-segmentation" / "column-warp" / "samples"


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


@pytest.mark.skipif(not GOLD.exists(), reason="需要 open-guji-dataset")
def test_gate_threshold_still_separates_the_human_verdicts():
    """`SIDE_FLOOR_MAX` 必须仍然把金标的 clean 和 mixed 分在两边。

    间隔很窄（clean 上限 0.0109 vs mixed 下限 0.0136，而 mixed 只有 n=2），
    所以任何一次调参、任何一次上游改列图，都该让这条先响。
    """
    import cv2
    from open_guji_cv.utils.column_projection import denoise_column
    lo, hi = [], []
    for f in sorted(GOLD.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        wf = (REPO / "output" / d["book"] / "step2_columns" / d["page"] / "windows.json")
        if not wf.exists() or d.get("verdict") not in ("clean", "mixed"):
            continue
        win = next((c for c in json.loads(wf.read_text(encoding="utf-8"))["columns"]
                    if c["col"] == d["col"]), None)
        if win is None:
            continue
        img = cv2.imread(str(wf.parent / win["file"]), cv2.IMREAD_GRAYSCALE)
        (lo if d["verdict"] == "clean" else hi).append(
            mod.side_floor(denoise_column(img)))
    if not lo or not hi:
        pytest.skip("金标里没有可比的 clean/mixed 列图")
    assert max(lo) <= mod.SIDE_FLOOR_MAX < min(hi), (
        f"clean 上限 {max(lo):.4f} / mixed 下限 {min(hi):.4f} / "
        f"门槛 {mod.SIDE_FLOOR_MAX}")
