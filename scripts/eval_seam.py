"""切缝墨率：格线是不是切在字上（char-segmentation/seam）。

「上下接壤」这类毛病——邻字的墨蹭进来、本字的尾巴被留在隔壁——根子都在
同一件事：**两格之间那一刀切在了笔画上**。这件事不需要人工标注就能量：
把列投影铺开，格线所在那一行的墨量除以上下两格字身的墨峰，比值越高，
说明这一刀越是从墨里穿过去的。

  切缝墨率 = 平滑列投影(格线 y) / max(min(上格峰, 下格峰), 0.35×本列峰中位)

分母取上下两格的**较小**峰：一刀只有同时挨着两边的字才叫「切在字上」；
再用本列峰中位兜底，免得稀疏邻格（一个「一」字）把比值放飞。

⚠️ 这条闸量的正是 `snap_bounds_to_gaps` 直接优化的目标，所以它**不能**
用来证明吸附/微挪本身是对的（那属于自考）——它的用途是**守住**：以后
任何改动都不许让重切缝变多。吸附本身的验证走 recrop/frame-strip/instances
这些独立闸 + 人眼 A/B。

用法：PYTHONPATH=. python scripts/eval_seam.py <数据集目录> [--update]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import cv2

from open_guji_cv.clustering.grid_segment import (
    deshear, column_projection, _smooth)

BASE_FLOOR = 0.35   # 分母下限（× 本列字峰中位）
HEAVY_T = 0.7       # 「重切缝」门槛：比值超此，这一刀基本贴着笔画走
PAGE_NEW_T = 3      # 单页重切缝比金标多这么多条 → 候选点名
# ……但只有**占比也变糟**才算真退步。页面被修好之后字格会变多（文字带
# 窗口救援一次给 vol02/108 多切了 17 格），切缝数跟着涨，重切缝的绝对
# 条数自然也涨——拿绝对条数罚它，等于罚它多切出了字。


def page_seams(book: str, page: str, out: str = "output") -> list[float]:
    gp = Path(out) / book / "phase3_char_grid" / f"{page}_char_grid.json"
    if not gp.exists():
        return []
    g = json.loads(gp.read_text(encoding="utf-8"))
    im = cv2.imread(f"{out}/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
    if im is None:
        return []
    im = deshear(im, g.get("grid", {}).get("shear", 0.0))
    cell_h = g.get("grid", {}).get("cell_h") or 100.0
    vals: list[float] = []
    for col in g.get("columns") or []:
        cells = [c for c in col.get("cells", []) if c.get("type") == "char"]
        if len(cells) < 2:
            continue
        x0 = max(0, int(col["left_x"]) + 2)
        x1 = min(im.shape[1], int(col["right_x"]) - 2)
        if x1 - x0 < 8:
            continue
        sm = _smooth(column_projection(im[:, x0:x1]), cell_h)
        L = len(sm)
        peaks = []
        for c in cells:
            h = c["y_bottom"] - c["y_top"]
            a = int(max(0, c["y_top"] + 0.2 * h))
            b = int(min(L, c["y_bottom"] - 0.2 * h))
            peaks.append(float(sm[a:b].max()) if b > a else 0.0)
        good = [p for p in peaks if p > 1]
        if not good:
            continue
        colmed = float(np.median(good))
        if colmed < 3:            # 整列几乎没墨，比值没有意义
            continue
        for i in range(len(cells) - 1):
            if abs(cells[i + 1]["y_top"] - cells[i]["y_bottom"]) > 2:
                continue          # 两格不相邻（中间隔着空格/margin）
            base = max(min(peaks[i], peaks[i + 1]), BASE_FLOOR * colmed)
            y = min(max(int(round(cells[i]["y_bottom"])), 0), L - 1)
            vals.append(float(sm[y]) / base)
    return vals


def scan(dataset: str, out: str = "output") -> dict:
    gold = json.loads((Path(dataset).parent / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    body = [(r["book"], r["page"]) for r in gold if r["page_type"] == "body"]
    pages: dict[str, int] = {}
    allv: list[float] = []
    rates: list[tuple] = []
    for book, page in sorted(body):
        v = page_seams(book, page, out)
        if not v:
            continue
        allv += v
        n = sum(1 for x in v if x >= HEAVY_T)
        rates.append((n / len(v), f"{book}/{page}", n, len(v)))
        if n:
            # 同时记总切缝数：单页比较必须按**占比**，不能按绝对条数
            pages[f"{book}/{page}"] = [n, len(v)]
    a = np.array(allv) if allv else np.zeros(1)
    # 页级分布：全书总数会把「少数页烂透」平均掉——vol01/60 单页 16.4%
    # 重切缝，全书总率却只有 0.6%。**先看页级分布，再看总数。**
    r = np.array([x[0] for x in rates]) if rates else np.zeros(1)
    rates.sort(reverse=True)
    return {
        "heavy_threshold": HEAVY_T,
        "n_seams": len(allv),
        "n_heavy": int((a >= HEAVY_T).sum()),
        "median": round(float(np.median(a)), 4),
        "p90": round(float(np.percentile(a, 90)), 4),
        "page_rate": {
            "n_pages": len(rates),
            "median": round(float(np.median(r)), 4),
            "p90": round(float(np.percentile(r, 90)), 4),
            "p99": round(float(np.percentile(r, 99)), 4),
            "n_ge_05": int((r >= 0.05).sum()),
            "n_ge_10": int((r >= 0.10).sum()),
            "n_ge_20": int((r >= 0.20).sum()),
            "worst": [[k, n, t, round(x, 4)] for x, k, n, t in rates[:20]],
        },
        "pages": pages,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    a = ap.parse_args()
    shard = Path(a.dataset) / "seam" / "expected.json"
    got = scan(a.dataset, a.out)
    if a.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标：切缝 {got['n_seams']}，重切缝 {got['n_heavy']} → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))
    print(f"切缝 {gold['n_seams']} → {got['n_seams']}")
    print(f"重切缝（≥{HEAVY_T}） {gold['n_heavy']} → {got['n_heavy']}   "
          f"中位 {gold['median']} → {got['median']}   "
          f"p90 {gold['p90']} → {got['p90']}")
    gr, tr = gold.get("page_rate") or {}, got.get("page_rate") or {}
    if tr:
        print("页级重切缝率（全书总数会把「少数页烂透」平均掉，先看这个）：")
        print(f"  中位 {gr.get('median','-')} → {tr['median']}   "
              f"p90 {gr.get('p90','-')} → {tr['p90']}   "
              f"p99 {gr.get('p99','-')} → {tr['p99']}")
        print(f"  ≥5% 的页 {gr.get('n_ge_05','-')} → {tr['n_ge_05']}   "
              f"≥10% {gr.get('n_ge_10','-')} → {tr['n_ge_10']}   "
              f"≥20% {gr.get('n_ge_20','-')} → {tr['n_ge_20']}")
        print("  最差 8 页：" + "  ".join(
            f"{k} {n}/{t}={x:.0%}" for k, n, t, x in tr["worst"][:8]))
    gp, tp = gold.get("pages", {}), got.get("pages", {})

    def pair(d, k):
        v = d.get(k)
        if v is None:
            return 0, 0
        return (v, 0) if isinstance(v, int) else (v[0], v[1])

    worse = []
    for k in sorted(tp):
        n_new, t_new = pair(tp, k)
        n_old, t_old = pair(gp, k)
        if n_new - n_old < PAGE_NEW_T:
            continue
        r_new = n_new / t_new if t_new else 1.0
        r_old = n_old / t_old if t_old else 0.0
        if r_new <= r_old:        # 切缝总数涨了、占比没涨 → 是修好带来的
            continue
        worse.append((k, n_old, t_old, n_new, t_new))
    for k, n_old, t_old, n_new, t_new in worse[:15]:
        print(f"  ✗ {k}：{n_old}/{t_old} → {n_new}/{t_new}")
    # 回归门也必须看页级：总数持平但「烂页」变多，等于把病灶挪了个地方
    page_bad = bool(tr) and bool(gr) and (
        tr["n_ge_10"] > gr.get("n_ge_10", 0)
        or tr["n_ge_20"] > gr.get("n_ge_20", 0))
    if page_bad:
        print(f"  ✗ 烂页变多：≥10% 的页 {gr.get('n_ge_10')} → {tr['n_ge_10']}，"
              f"≥20% 的页 {gr.get('n_ge_20')} → {tr['n_ge_20']}")
    ok = got["n_heavy"] <= gold["n_heavy"] and not worse and not page_bad
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
