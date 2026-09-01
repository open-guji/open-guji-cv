# -*- coding: utf-8 -*-
"""拿 column-warp 金标量 Step2（单列矫正 + 界行清除）的准确度。

    python scripts/eval_column_warp.py ../open-guji-dataset/char-segmentation/column-warp

金标的边界**不是一个点而是一条走廊** `[canonical, human]`（用户明说标定的坐标
不唯一，只要墨量接近 0、越靠外越好）。所以尺子按走廊来，**吃字和留残墨分开报**
——代价完全不对称：留一点界行残墨下游还能救，切掉的字身墨谁也补不回来。

  1. 落在走廊内   pred 在 [canonical, human] 之间 = 对，误差记 0。
  2. 吃进字身     pred 越过 human 往里 = 把字身当界行清掉了（px）。
  3. 留下残墨     pred 没推到 canonical = 界行残墨留在带里（px + 那一段的墨量）。

上下版框那部分的金标**只记类别不记坐标**（clean/glued/none/idk），所以按类别
混淆矩阵报，不算像素误差。

按人裁的 verdict 分组报：只有 `clean`（人认为界行残墨和字身墨分得开）那组才是
位置精度基准；`mixed` 组人已经判定「做不到两者兼得」，那组的边界误差说明不了
算法准不准，只能说明这些列**矫正得不够好**——它们本身就是待修的失败样本。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.border_geometry import VLine  # noqa: E402
from open_guji_cv.utils.column_projection import (  # noqa: E402
    clean_column,
    column_profile,
    column_text_band,
    denoise_column,
    warp_column,
)

SRC = ROOT / "data_full" / "zongmu" / "{book}" / "{page}.png"


def rebuild(sample: dict) -> np.ndarray:
    """取这条金标标注时看的那张列图。

    新口径（`input.variant = detected_lines@per_column_window`）直接读
    `regen_step2_columns.py` 产的列图；`legacy-page-anchor/` 那套旧金标没有
    列图文件，按样本里存的几何量现算。**两套不能混着比**——边线一个来自
    人工金标、一个来自算法探测，实测差 0.76~27.6px。"""
    if "input" not in sample:
        # 只有 border_class 的样本（文字带待重标）没存 input 块，按定版输入现找
        wf = (ROOT / "output" / sample["book"] / "step2_columns" / sample["page"]
              / "windows.json")
        if wf.exists():
            win = next(c for c in json.loads(wf.read_text(encoding="utf-8"))["columns"]
                        if c["col"] == sample["col"])
            return denoise_column(cv2.imread(str(wf.parent / win["file"]),
                                              cv2.IMREAD_GRAYSCALE))
    if "input" in sample:
        p = ROOT / sample["input"]["column_image"].replace("open-guji-cv ", "")
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise SystemExit(f"读不到列图 {p}——先跑 scripts/regen_step2_columns.py")
        return denoise_column(img)
    g = sample["geometry"]
    gray = cv2.imread(str(SRC).format(book=sample["book"], page=sample["page"]),
                       cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f"读不到原始扫描 {sample['book']}/{sample['page']}")
    left = VLine(g["left_line"]["x_at_top"], g["left_line"]["slope"])
    right = VLine(g["right_line"]["x_at_top"], g["right_line"]["slope"])
    return denoise_column(warp_column(gray, left, right, g["top_y"], g["bottom_y"]))


def measure(sample: dict) -> dict:
    warped = rebuild(sample)
    tb = sample["text_band"]
    hl, hr = tb["human_left"], tb["human_right"]
    cl, cr = tb["canonical_left"], tb["canonical_right"]
    pl, pr = column_text_band(warped)
    prof = column_profile(warped)

    def ink(lo: int, hi: int) -> float:
        return float(prof[lo:hi].mean()) if hi > lo else 0.0

    return dict(
        book=sample["book"], page=sample["page"], col=sample["col"],
        verdict=sample["verdict"], tags=sample["tags"], w=warped.shape[1],
        in_corridor_left=cl <= pl <= hl, in_corridor_right=hr <= pr <= cr,
        # 越过 human 往里 = 吃字（左界比 human 大 / 右界比 human 小）
        eaten_left=max(0, pl - hl), eaten_right=max(0, hr - pr),
        # 没推到 canonical = 残墨留在带里
        short_left=max(0, cl - pl), short_right=max(0, pr - cr),
        residue_ink=max(ink(pl, cl), ink(cr, pr)),
        corridor_left=hl - cl, corridor_right=cr - hr,
        # 人标带外的墨占比：界行残墨的绝对量，与算法无关
        gold_outside_ink=max(ink(0, cl), ink(cr, warped.shape[1])),
    )


def stat(vals: list[float], fmt: str = "%.1f") -> str:
    if not vals:
        return "—"
    return (f"{fmt % statistics.mean(vals)} / {fmt % statistics.median(vals)} / "
            f"{fmt % max(vals)}")


def report(rows: list[dict]) -> None:
    print(f"样本 {len(rows)} 列 / {len({(r['book'], r['page']) for r in rows})} 页")
    order = ["clean", "mixed", "idk"]
    groups = [(v, [r for r in rows if r["verdict"] == v]) for v in order]
    groups = [(v, g) for v, g in groups if g] + [("全部", rows)]

    print("\n（每格 = 均值 / 中位 / 最大）")
    head = ("分组", "n", "落在走廊内", "吃进字身px", "差多少到走廊px", "留下的残墨")
    print(f"{head[0]:<8}{head[1]:>4} | {head[2]:^11} | {head[3]:^19} | "
          f"{head[4]:^19} | {head[5]:^21}")
    for name, g in groups:
        hit = sum(r["in_corridor_left"] + r["in_corridor_right"] for r in g)
        eaten = [r["eaten_left"] + r["eaten_right"] for r in g]
        short = [r["short_left"] + r["short_right"] for r in g]
        resid = [r["residue_ink"] for r in g]
        print(f"{name:<8}{len(g):>4} | {f'{hit}/{2 * len(g)} 条界':^11} | "
              f"{stat(eaten):^19} | {stat(short):^19} | {stat(resid, '%.3f'):^21}")

    n_eat = sum(1 for r in rows if r["eaten_left"] + r["eaten_right"] > 0)
    print(f"\n吃到字身的列：{n_eat} / {len(rows)}"
          f"（宁可留残墨也不切字，这个数应该压到 0）")
    print(f"走廊宽度（human 到 canonical 有多少 px 余地）："
          f"{stat([r['corridor_left'] for r in rows])} 左 / "
          f"{stat([r['corridor_right'] for r in rows])} 右")
    print("金标 canonical 之外的墨占比（界行残墨的绝对量，与算法无关）："
          f"{stat([r['gold_outside_ink'] for r in rows], '%.3f')}")

    worst = sorted(rows, key=lambda r: -(r["eaten_left"] + r["eaten_right"]
                                          + r["short_left"] + r["short_right"]))[:8]
    print("\n偏出走廊最多的 8 列：")
    for r in worst:
        print(f"  {r['book']}/{r['page']} c{r['col']:<2} 宽{r['w']:>4} "
              f"吃{r['eaten_left'] + r['eaten_right']:>3} "
              f"欠{r['short_left'] + r['short_right']:>3}  "
              f"[{r['verdict']}] {'/'.join(r['tags'])}")

    by_tag: dict[str, list[dict]] = {}
    for r in rows:
        for t in r["tags"]:
            by_tag.setdefault(t, []).append(r)
    print("\n按选列标签（同一列可能挂多个标签，行间会重叠）：")
    for t, g in sorted(by_tag.items(), key=lambda kv: -len(kv[1])):
        off = [r["eaten_left"] + r["eaten_right"] + r["short_left"] + r["short_right"]
               for r in g]
        hit = sum(r["in_corridor_left"] + r["in_corridor_right"] for r in g)
        mixed = sum(1 for r in g if r["verdict"] == "mixed")
        print(f"  {t:<12} n={len(g):>3}  偏出走廊 {stat(off)}  "
              f"命中 {hit}/{2 * len(g)}  判「分不开」{mixed}")


# 算法档 -> 人裁类别。a(贴边) 和 d(内缩) 都是"有版框残墨且有间隙"，人看不出
# 也不需要分——切在哪一行算法自己算得准，人只判有没有间隙。
CASE_TO_CLASS = {"a": "clean", "d": "clean", "b": "glued", "c": "none"}


def report_border(samples: list[dict]) -> None:
    """上下版框分档的准确度：金标只记类别，所以按类别混淆矩阵报。"""
    graded = [s for s in samples if s.get("border_class")]
    if not graded:
        print("\n（还没有 border_class 金标，跳过上下版框那部分）")
        return
    rows = []
    for s in graded:
        _, diag = clean_column(rebuild(s))
        for end in ("top", "bottom"):
            gold = s["border_class"].get(end)
            if not gold:
                continue
            case = diag[end]["case"]
            rows.append((s, end, case, CASE_TO_CLASS[case], gold, diag[end]["px"]))

    scored = [r for r in rows if r[4] != "idk"]
    agree = sum(1 for r in scored if r[3] == r[4])
    print(f"\n上下版框分档：{len(graded)} 列 / {len(rows)} 条端裁决"
          f"（其中 idk {len(rows) - len(scored)} 条不计分）")
    print(f"  一致 {agree} / {len(scored)}")
    labels = ["clean", "glued", "none"]
    header = "金标\\自动"
    print("\n  " + f"{header:<10}" + "".join(f"{c:>8}" for c in labels))
    for g in labels:
        line = "".join(
            f"{sum(1 for r in scored if r[4] == g and r[3] == p):>8}" for p in labels)
        print(f"  {g:<10}" + line)
    bad = [r for r in scored if r[3] != r[4]]
    if bad:
        print("\n  不一致的：")
        for s, end, case, pred, gold, px in bad:
            print(f"    {s['book']}/{s['page']} c{s['col']} {end:<6} "
                  f"自动={case}({pred}, 削{px}行)  金标={gold}")
    cases = {}
    for _, end, case, *_ in rows:
        cases[(end, case)] = cases.get((end, case), 0) + 1
    print("\n  算法分档分布：" + "  ".join(
        f"{e}·{c}={n}" for (e, c), n in sorted(cases.items())))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="column-warp 子集目录")
    args = ap.parse_args()
    files = sorted((Path(args.dataset) / "samples").glob("*.json"))
    if not files:
        raise SystemExit(f"{args.dataset}/samples 里没有样本")
    samples = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    # 有些样本只有 border_class（文字带被上游改动作废、等重标），跳过带那部分
    banded = [s for s in samples if s.get("text_band")]
    if banded:
        report([measure(s) for s in banded])
        pending = len(samples) - len(banded)
        if pending:
            print(f"\n另有 {pending} 列只有 border_class、文字带待重标，未计入上表")
    report_border(samples)


if __name__ == "__main__":
    main()
