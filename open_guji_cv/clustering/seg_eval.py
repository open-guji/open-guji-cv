"""单字分拆·格内净化 Benchmark：不同归属算法的可复现对比。

问题：图块里混入左右界行/版框，或上下邻字的小块残余。
难点：不能用「间隙阈值」判断——实测污染块与本字分离部件的间隙分布
      （污染 p50=10px / 「高卞示」顶部部件 p50=12px）**完全重叠**，
      任何阈值都必然误伤。所以本模块把评测拆成两个互相拉扯的指标：

  keep_recall     本字墨迹保住的比例  ← 误删「高/卞/示」顶部的点就掉这里
  drop_precision  留下的墨里本字占比  ← 混入界行/邻字残余就掉这里

任何算法只要实现 Strategy 签名即可挂进来反复测：

    (strip, cells, cell_h, col_w) -> {格序号: 该格保留的墨迹布尔掩膜}

金标来源（metadata 的 label_origin）：
  synth  由「结构上确定干净」的真实格位合成整列，再注入已知位置的
         界行与邻字残余——逐像素金标，可大量生成，且刻意保留顶部
         分离部件的样本作为关键正例；
  human  人工审查 flag（contaminated / truncated）的真实实例。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .extractor import (MIN_COMP_AREA_RATIO, PADDING_RATIO, _assign_column,
                        _column_binary)

Cells = list[tuple[int, float, float]]
Masks = dict[int, np.ndarray]
Strategy = Callable[[np.ndarray, Cells, float, float], Masks]

# ── 策略 ──────────────────────────────────────────────────

def strat_padding_box(strip: np.ndarray, cells: Cells,
                      cell_h: float, col_w: float) -> Masks:
    """旧做法：按格线裁框 + 固定纵向外扩，框内墨迹全收。

    留作基线——它对分离部件零误伤（recall 必为 1），代价是把界行和
    邻字残余一并收进来，drop_precision 就是它的短板。
    """
    ink = _column_binary(strip).astype(bool)
    h = strip.shape[0]
    out: Masks = {}
    for i, top, bot in cells:
        pad = (bot - top) * PADDING_RATIO
        y0 = max(0, int(round(top - pad)))
        y1 = min(h, int(round(bot + pad)))
        m = np.zeros_like(ink)
        m[y0:y1] = ink[y0:y1]
        out[i] = m
    return out


def strat_gap_threshold(strip: np.ndarray, cells: Cells,
                        cell_h: float, col_w: float,
                        gap: float = 0.10) -> Masks:
    """对照组：裁框后再按「与主体的纵向间隙 > gap×格高」丢弃孤立块。

    这是最容易想到的做法，收进来就是为了用数据证明它不行：它必然
    误伤「高/卞/示」顶部与主体不连通的点/横。
    """
    ink = _column_binary(strip)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    h = strip.shape[0]
    out: Masks = {}
    for i, top, bot in cells:
        pad = (bot - top) * PADDING_RATIO
        y0 = max(0, int(round(top - pad)))
        y1 = min(h, int(round(bot + pad)))
        comps = []
        for k in range(1, n):
            x, y, cw, ch, area = stats[k]
            if area < MIN_COMP_AREA_RATIO * cell_h * col_w:
                continue
            if y >= y1 or y + ch <= y0:
                continue
            comps.append((k, y, y + ch, area))
        m = np.zeros(labels.shape, bool)
        if comps:
            main = max(comps, key=lambda c: c[3])
            for k, cy0, cy1, _a in comps:
                d = max(main[1] - cy1, cy0 - main[2], 0)
                if k != main[0] and d > gap * cell_h:
                    continue
                sub = labels == k
                sub[:y0] = False
                sub[y1:] = False
                m |= sub
        out[i] = m
    return out


def strat_component_owner(strip: np.ndarray, cells: Cells,
                          cell_h: float, col_w: float) -> Masks:
    """本项目采用：列级连通体归属（详见 extractor._assign_column）。

    判据是「这块墨的主体落在谁的格子里」，间隙大小完全不参与。
    """
    _boxes, owner = _assign_column(strip, cells, cell_h, col_w)
    return {i: (owner == i + 1) for i, _t, _b in cells}


STRATEGIES: dict[str, Strategy] = {
    "padding_box": strat_padding_box,
    "gap_threshold": strat_gap_threshold,
    "component_owner": strat_component_owner,
}


# ── 评分 ──────────────────────────────────────────────────

@dataclass
class CellScore:
    cell: int
    keep_recall: float      # 本字墨迹保住比例
    drop_precision: float   # 留下的墨中本字占比
    gold_px: int
    pred_px: int
    tags: list[str] = field(default_factory=list)

    @property
    def f1(self) -> float:
        r, p = self.keep_recall, self.drop_precision
        return 0.0 if r + p == 0 else 2 * r * p / (r + p)


def score_cell(pred: np.ndarray, gold: np.ndarray,
               cell: int, tags: list[str] | None = None) -> CellScore:
    g = int(gold.sum())
    p = int(pred.sum())
    inter = int((pred & gold).sum())
    return CellScore(
        cell=cell,
        keep_recall=1.0 if g == 0 else inter / g,
        drop_precision=1.0 if p == 0 else inter / p,
        gold_px=g, pred_px=p, tags=list(tags or []),
    )


def aggregate(scores: list[CellScore]) -> dict:
    """汇总。intact_rate 是硬指标——分离部件被削掉一个像素就不算完好。"""
    if not scores:
        return {"n": 0}
    n = len(scores)
    return {
        "n": n,
        "keep_recall": round(sum(s.keep_recall for s in scores) / n, 4),
        "drop_precision": round(sum(s.drop_precision for s in scores) / n, 4),
        "f1": round(sum(s.f1 for s in scores) / n, 4),
        "intact_rate": round(sum(s.keep_recall > 0.999 for s in scores) / n, 4),
        "clean_rate": round(sum(s.drop_precision > 0.999 for s in scores) / n, 4),
    }


# ── 样本 IO ───────────────────────────────────────────────

def load_case(sample_dir: Path) -> dict:
    """读一个样本目录：strip.png + case.json（金标为逐格连通体白名单）。"""
    sample_dir = Path(sample_dir)
    meta = json.loads((sample_dir / "case.json").read_text(encoding="utf-8"))
    strip = cv2.imread(str(sample_dir / "strip.png"), cv2.IMREAD_GRAYSCALE)
    gold_img = cv2.imread(str(sample_dir / "gold.png"), cv2.IMREAD_GRAYSCALE)
    cells = [(int(c["index"]), float(c["y_top"]), float(c["y_bottom"]))
             for c in meta["cells"]]
    # gold.png 用像素值编码归属：0=非本字墨/背景，i+1=第 i 格
    gold = {i: (gold_img == i + 1) for i, _t, _b in cells}
    return {"strip": strip, "cells": cells, "gold": gold, "meta": meta,
            "cell_h": float(meta["cell_h"]), "col_w": float(meta["col_w"])}


def run_case(case: dict, strategy: Strategy) -> list[CellScore]:
    pred = strategy(case["strip"], case["cells"],
                    case["cell_h"], case["col_w"])
    tags = {int(c["index"]): c.get("tags", []) for c in case["meta"]["cells"]}
    return [score_cell(pred.get(i, np.zeros_like(case["gold"][i])),
                       case["gold"][i], i, tags.get(i))
            for i, _t, _b in case["cells"]]


def run_dataset(samples_dir: Path,
                strategies: dict[str, Strategy] | None = None) -> dict:
    """跑整个数据集，返回 {策略: 汇总}，另附关键子集 detached_top 的单独汇总。"""
    strategies = strategies or STRATEGIES
    cases = [d for d in sorted(Path(samples_dir).iterdir())
             if (d / "case.json").exists()]
    report: dict = {"n_cases": len(cases), "strategies": {}}
    for name, fn in strategies.items():
        all_s: list[CellScore] = []
        for d in cases:
            all_s.extend(run_case(load_case(d), fn))
        sub = [s for s in all_s if "detached_top" in s.tags]
        report["strategies"][name] = {
            "overall": aggregate(all_s),
            "detached_top": aggregate(sub),
            "contaminated": aggregate([s for s in all_s
                                       if "contaminated" in s.tags]),
        }
    return report


def format_report(report: dict) -> str:
    rows = ["策略              n    keep_recall  drop_prec   f1     完好率  纯净率",
            "-" * 74]
    for name, r in report["strategies"].items():
        o = r["overall"]
        rows.append(f"{name:<16} {o['n']:>5} {o['keep_recall']:>11.4f} "
                    f"{o['drop_precision']:>10.4f} {o['f1']:>6.4f} "
                    f"{o['intact_rate']:>7.4f} {o['clean_rate']:>7.4f}")
    rows.append("")
    rows.append("关键子集 detached_top（顶部部件与主体不连通：高 / 卞 / 示）")
    rows.append("-" * 74)
    for name, r in report["strategies"].items():
        d = r["detached_top"]
        if d.get("n"):
            rows.append(f"{name:<16} {d['n']:>5} {d['keep_recall']:>11.4f} "
                        f"{d['drop_precision']:>10.4f} {d['f1']:>6.4f} "
                        f"{d['intact_rate']:>7.4f} {d['clean_rate']:>7.4f}")
    return "\n".join(rows)
