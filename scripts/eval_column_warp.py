# -*- coding: utf-8 -*-
"""拿 column-warp 金标量 Step2（单列矫正 + 界行清除）的准确度。

    python scripts/eval_column_warp.py ../open-guji-dataset/char-segmentation/column-warp

三把尺子，**吃字和留残墨分开报**——代价完全不对称：留一点界行残墨下游还能救，
切掉的字身墨谁也补不回来。

  1. 边界误差   |pred - gold|，左右两条分别算（px）。
  2. 吃进字身   pred 比 gold 窄的那部分，也就是被误当界行清掉的字身区域（px）。
  3. 留下残墨   gold 带外、pred 带内那一段里的墨量——没清干净的界行（墨占比）。

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
    column_profile,
    column_text_band,
    denoise_column,
    warp_column,
)

SRC = ROOT / "data_full" / "zongmu" / "{book}" / "{page}.png"


def rebuild(sample: dict) -> np.ndarray:
    """按样本里存的几何量重算矫正图——金标不依赖任何中间产物文件。"""
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
    gl, gr = sample["text_band"]["x_left"], sample["text_band"]["x_right"]
    pl, pr = column_text_band(warped)
    prof = column_profile(warped)

    def outside_ink(lo: int, hi: int) -> float:
        """[lo,hi) 里的平均墨占比；空区间算 0。"""
        return float(prof[lo:hi].mean()) if hi > lo else 0.0

    return dict(
        book=sample["book"], page=sample["page"], col=sample["col"],
        verdict=sample["verdict"], tags=sample["tags"], w=warped.shape[1],
        err_left=abs(pl - gl), err_right=abs(pr - gr),
        # 预测带比金标窄 = 把字身当界行清掉了
        eaten_left=max(0, pl - gl), eaten_right=max(0, gr - pr),
        # 预测带比金标宽 = 界行残墨留在带里没清掉；用那一段的墨量衡量
        left_residue=outside_ink(pl, gl) if gl > pl else 0.0,
        right_residue=outside_ink(gr, pr) if pr > gr else 0.0,
        # 人标的带外还剩多少墨——这是"界行残墨到底有多少"的绝对量，跟算法无关
        gold_outside_ink=max(outside_ink(0, gl), outside_ink(gr, warped.shape[1])),
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
    head = ("分组", "n", "左界误差px", "右界误差px", "吃进字身px", "残墨墨占比")
    print(f"{head[0]:<8}{head[1]:>4} | {head[2]:^19} | {head[3]:^19} | "
          f"{head[4]:^19} | {head[5]:^21}")
    for name, g in groups:
        eaten = [r["eaten_left"] + r["eaten_right"] for r in g]
        resid = [max(r["left_residue"], r["right_residue"]) for r in g]
        print(f"{name:<8}{len(g):>4} | {stat([r['err_left'] for r in g]):^19} | "
              f"{stat([r['err_right'] for r in g]):^19} | "
              f"{stat(eaten):^19} | {stat(resid, '%.3f'):^21}")

    n_eat = sum(1 for r in rows if r["eaten_left"] + r["eaten_right"] > 0)
    print(f"\n吃到字身的列：{n_eat} / {len(rows)}"
          f"（宁可留残墨也不切字，这个数应该压到 0）")
    print("金标带外的墨占比（界行残墨的绝对量，与算法无关）："
          f"{stat([r['gold_outside_ink'] for r in rows], '%.3f')}")

    worst = sorted(rows, key=lambda r: -(r["err_left"] + r["err_right"]))[:8]
    print("\n误差最大的 8 列：")
    for r in worst:
        print(f"  {r['book']}/{r['page']} c{r['col']:<2} 宽{r['w']:>4} "
              f"左{r['err_left']:>3} 右{r['err_right']:>3} "
              f"吃{r['eaten_left'] + r['eaten_right']:>3}  "
              f"[{r['verdict']}] {'/'.join(r['tags'])}")

    by_tag: dict[str, list[dict]] = {}
    for r in rows:
        for t in r["tags"]:
            by_tag.setdefault(t, []).append(r)
    print("\n按选列标签（同一列可能挂多个标签，行间会重叠）：")
    for t, g in sorted(by_tag.items(), key=lambda kv: -len(kv[1])):
        errs = [r["err_left"] + r["err_right"] for r in g]
        mixed = sum(1 for r in g if r["verdict"] == "mixed")
        print(f"  {t:<12} n={len(g):>3}  边界误差合计 {stat(errs)}  "
              f"判「分不开」{mixed}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="column-warp 子集目录")
    args = ap.parse_args()
    files = sorted((Path(args.dataset) / "samples").glob("*.json"))
    if not files:
        raise SystemExit(f"{args.dataset}/samples 里没有样本")
    report([measure(json.loads(f.read_text(encoding="utf-8"))) for f in files])


if __name__ == "__main__":
    main()
