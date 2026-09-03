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


def _clean_vs_mixed_side_floor() -> tuple[list[float], list[float]]:
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
    return lo, hi


@pytest.mark.skipif(not GOLD.exists(), reason="需要 open-guji-dataset")
@pytest.mark.xfail(strict=True, reason=(
    "负结果（2026-09-02 扩金标后坐实）：「两侧最低墨」这一条单一指标已经不能"
    "分开 clean/mixed —— 114 列金标复核：clean 上到 0.0417、mixed 低到 0.0038，"
    "完全重叠，扫遍所有门槛最优也只能误杀 3 / 放过 1。原因是这条判据"
    "结构上只看两侧外 25% 的墨——vol01/151 c4 那种「弯界行只在列中段探入」和"
    "vol02/3 c9 那种「背景印章导致整列散布噪点、不集中在边缘」，这两种污染"
    "side_floor 天生看不见。见 test_side_floor_cannot_see_whole_column_contamination。"
    "如果这条哪天意外 PASS 了，不代表判据修好了，先去查是不是金标又漂了"
    "（比如某次上游改动让样本对应的列图变了但没重标）。"))
def test_gate_threshold_still_separates_the_human_verdicts():
    """`SIDE_FLOOR_MAX` 曾经能把金标的 clean 和 mixed 分在两边（clean 上限
    0.0109 vs mixed 下限 0.0136，n=2），现在不能了——标成 `xfail` 而不是删掉，
    是为了留一个「这条判据啥时候好使、啥时候不好使」的活证据。
    """
    lo, hi = _clean_vs_mixed_side_floor()
    if not lo or not hi:
        pytest.skip("金标里没有可比的 clean/mixed 列图")
    assert max(lo) <= mod.SIDE_FLOOR_MAX < min(hi), (
        f"clean 上限 {max(lo):.4f} / mixed 下限 {min(hi):.4f} / "
        f"门槛 {mod.SIDE_FLOOR_MAX}")


@pytest.mark.skipif(not GOLD.exists(), reason="需要 open-guji-dataset")
def test_side_floor_cannot_see_whole_column_contamination():
    """记录 `side_floor` 结构性看不见的两种污染，别再拿它当全能判据。

    `side_floor` 只量两侧外 25% —— 污染要是不贴边（弯界行只在列中段探入、
    背景印章整列散布噪点）就测不到。这不是参数没调好，是这条尺子的设计
    范围本来就只覆盖「贴边」这一种形态。**扩大金标不会把这条测挽救回来**，
    需要的是另一条独立于「两侧墨量」的判据（比如整列噪点密度/连通域特征）。
    """
    lo, hi = _clean_vs_mixed_side_floor()
    if not lo or not hi:
        pytest.skip("金标里没有可比的 clean/mixed 列图")
    assert min(hi) <= max(lo), (
        "如果这条也开始失败，说明 side_floor 又能分开了——"
        "去看金标是不是漂了，而不是庆祝判据修好了")
