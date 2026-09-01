"""字身截断率：格线切进字身多深（char-segmentation/truncation）。

**这是用户看图时最先看见的毛病，而原有的闸都量不出它。**
2026-08-26 用户实审 vol01/50、60 反馈「问题还是很多，太多截断」，
逐格核对属实：vol01/60 上 163 个单字墨段里 **150 个被格线切开**（92%），
而同一页 `eval_seam.py` 只报 16.4%、抽样正确率报到 99.25%。

为什么旧尺子看不见：

- `eval_seam` 量的是**平滑列投影在格线那一行的墨量比值**，门槛 0.7。
  笔画稀疏处（字的上缘只有一横的两端）切下去，平滑后墨量比值上不了
  0.7，这一刀就不算「重切缝」——可人眼看到的是字头被削掉一条。
- 抽样正确率量的是「这一格装的是不是一个完整的字」，缩略图上削掉
  10~20px 的边看不出来，判读一路判成 clean。

这条尺子直接量**字身**：列投影上取「单字墨段」（高 0.45~1.35 格，
太短是碎屑、太长是上下粘连），再看有没有格线落在段内、切进去多深，
深度按**本段高度**归一（字有大有小，绝对像素不可比）。

  截断深度 = min(格线 - 段顶, 段底 - 格线) / 段高

⚠️ 这条尺子**不是** `snap_bounds_to_gaps` 直接优化的目标（那个优化的是
格线处的平滑墨量），所以它既能守也能证；但它和 seam 有相关性，两条一起看。
⚠️ 它只看「切没切进字身」，**不看**有没有丢字、一格装没装两字——
那两件事分别归 `check_grid_offpage` 与 recrop/instances。

用法：PYTHONPATH=. python scripts/eval_truncation.py <数据集目录> [--update]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.grid_segment import deshear

RUN_INK = 0.06      # 行墨率达此值算「有墨行」（× 列宽）
RUN_MIN_H = 14      # 短于此的游程是碎屑/框条
RUN_GAP = 6         # 间隙小于此的两段并成一段（字内断笔）
SEG_LO, SEG_HI = 0.45, 1.35   # 「单字段」的高度窗（× 格高）
DEPTH_T = 0.10      # 主口径：切进 ≥ 此比例字高才算截断
EDGE_TOL = 3        # 格线离段端这么近不算切（量化/抗锯齿）


def col_runs(col: dict, im: np.ndarray, cell_h: float) -> list[list[int]]:
    x0 = int(col["left_x"]) + 4
    x1 = int(col["right_x"]) - 4
    if x1 - x0 < 8:
        return []
    prof = (im[:, x0:x1] < 128).sum(axis=1).astype(float)
    on = prof > (x1 - x0) * RUN_INK
    out: list[list[int]] = []
    s = None
    for y, v in enumerate(on):
        if v and s is None:
            s = y
        elif not v and s is not None:
            out.append([s, y - 1])
            s = None
    if s is not None:
        out.append([s, len(on) - 1])
    out = [r for r in out if r[1] - r[0] >= RUN_MIN_H]
    merged: list[list[int]] = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= RUN_GAP:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [r for r in merged
            if SEG_LO * cell_h <= r[1] - r[0] <= SEG_HI * cell_h]


def page_depths(book: str, page: str, out: str = "output") -> list[float]:
    gp = Path(out) / book / "phase3_char_grid" / f"{page}_char_grid.json"
    if not gp.exists():
        return []
    g = json.loads(gp.read_text(encoding="utf-8"))
    im = cv2.imread(f"{out}/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
    if im is None:
        return []
    im = deshear(im, g.get("grid", {}).get("shear", 0.0) or 0.0)
    cell_h = (g.get("grid") or {}).get("cell_h") or 115.0
    depths: list[float] = []
    for col in g.get("columns") or []:
        cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
        if len(cells) < 2:
            continue
        lines = [c["y_top"] for c in cells] + [cells[-1]["y_bottom"]]
        for a, b in col_runs(col, im, cell_h):
            h = float(b - a)
            d = 0.0
            for y in lines:
                if a + EDGE_TOL < y < b - EDGE_TOL:
                    d = max(d, min(y - a, b - y))
            depths.append(d / h)
    return depths


def scan(dataset: str, out: str = "output") -> dict:
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    body = [(r["book"], str(r["page"])) for r in gold
            if r["page_type"] == "body"]
    allv: list[float] = []
    rates: list[tuple] = []
    for book, page in sorted(body):
        d = page_depths(book, page, out)
        if not d:
            continue
        allv += d
        n = sum(1 for x in d if x >= DEPTH_T)
        rates.append((n / len(d), f"{book}/{page}", n, len(d)))
    a = np.array(allv) if allv else np.zeros(1)
    r = np.array([x[0] for x in rates]) if rates else np.zeros(1)
    rates.sort(reverse=True)
    return {
        "depth_threshold": DEPTH_T,
        "n_segs": len(allv),
        "n_cut_05": int((a >= 0.05).sum()),
        "n_cut_10": int((a >= 0.10).sum()),
        "n_cut_20": int((a >= 0.20).sum()),
        "n_cut_30": int((a >= 0.30).sum()),
        # 缺陷按页扎堆，全书率会把「几页烂透」平均掉——页级分布是第一位的
        "page_rate": {
            "n_pages": len(rates),
            "median": round(float(np.median(r)), 4),
            "p90": round(float(np.percentile(r, 90)), 4),
            "p99": round(float(np.percentile(r, 99)), 4),
            "n_ge_10": int((r >= 0.10).sum()),
            "n_ge_25": int((r >= 0.25).sum()),
            "n_ge_50": int((r >= 0.50).sum()),
            "worst": [[k, n, t, round(x, 4)] for x, k, n, t in rates[:25]],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    got = scan(a.dataset, a.out)
    shard = Path(a.dataset) / "truncation" / "expected.json"
    if a.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标：单字段 {got['n_segs']}，"
              f"截断(≥{DEPTH_T:.0%}) {got['n_cut_10']} → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))
    print(f"单字段 {gold['n_segs']} → {got['n_segs']}")
    for k, lab in (("n_cut_05", "≥5%"), ("n_cut_10", "≥10%"),
                   ("n_cut_20", "≥20%"), ("n_cut_30", "≥30%")):
        print(f"  切进 {lab:>5} 字高： {gold[k]} → {got[k]}"
              f"  （{got[k] / max(1, got['n_segs']):.2%}）")
    gr, tr = gold.get("page_rate") or {}, got.get("page_rate") or {}
    print("页级截断率（先看这个——烂页是扎堆的）：")
    print(f"  中位 {gr.get('median', '-')} → {tr['median']}   "
          f"p90 {gr.get('p90', '-')} → {tr['p90']}   "
          f"p99 {gr.get('p99', '-')} → {tr['p99']}")
    print(f"  ≥10% 的页 {gr.get('n_ge_10', '-')} → {tr['n_ge_10']}   "
          f"≥25% {gr.get('n_ge_25', '-')} → {tr['n_ge_25']}   "
          f"≥50% {gr.get('n_ge_50', '-')} → {tr['n_ge_50']}")
    print("  最差 10 页：" + "  ".join(
        f"{k} {n}/{t}={x:.0%}" for k, n, t, x in tr["worst"][:10]))
    ok = (got["n_cut_10"] <= gold["n_cut_10"]
          and got["n_cut_20"] <= gold["n_cut_20"]
          and tr["n_ge_25"] <= gr.get("n_ge_25", 0)
          and tr["n_ge_50"] <= gr.get("n_ge_50", 0))
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
