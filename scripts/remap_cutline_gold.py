"""切线金标按列窗几何**精确重映射**：旧列图行号 → 页面坐标 → 新列图行号。

**为什么不能平移**（2026-09-20 实测）：`warp_column` 是梯形→矩形的单应变换，列图的
y 映射随梯形形状**非线性**变化——两条边线在顶/底的 x 动十几像素，列图中段的行号就差
几十像素（vol02 界行重定位的 31 条金标 ≤10px 89.7% → 32.3%，误差 23~44px，而列窗
top/bottom 一个没动）。三段折线页更是每带一个矩阵。所以金标存在列图坐标里，**任何**
边线几何变化都不是平移。`reshift_cutline_gold.py` 只对「只有 top_y 动」成立。

**为什么能精确重映射**：矩阵的源四边形顶边、底边都是水平的，页面上的横线映射到列图
仍是横线——一条切线的行号与 x 无关，可以用列中线一点代表：
    r_old --inv(M_old)--> (x, y)_page --M_new--> r_new
折线逐点同样处理（x 也跟着 out_w 归一化）。需要重跑前的 `column_warp` 产物备份当旧几何。

用法：
    python scripts/remap_cutline_gold.py --book vol02 --windows-bak products/vol02/column_warp.bak-20260920
    python scripts/remap_cutline_gold.py --book vol02 --windows-bak ... --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.products.kinds.borders import VLineRec  # noqa: E402
from open_guji_cv.utils.column_projection import _strip_bounds, column_warp_matrix  # noqa: E402

SHARD = Path(r"D:\workspace\open-guji-dataset\char-segmentation\touching-cuts\items.jsonl")
GEOM_KEYS = ("left_line", "right_line", "top_y", "bottom_y")


def load_windows(d: Path) -> dict[int, tuple[int, dict[int, dict]]]:
    out = {}
    for f in sorted(d.glob("p0*.json")):
        try:
            cw = json.loads(f.read_text(encoding="utf-8"))["column_windows"]
        except (KeyError, json.JSONDecodeError):
            continue
        page_w = int(cw["page_size"][0]) if cw.get("page_size") else None
        out[int(f.stem[1:])] = (page_w, {c["col"]: c for c in cw["columns"]})
    return out


class Geom:
    """一列的射影几何：分带矩阵 + 行号偏移。"""

    def __init__(self, rec: dict, page_w: int):
        self.left = VLineRec(**rec["left_line"]).to_vline()
        self.right = VLineRec(**rec["right_line"]).to_vline()
        self.top, self.bottom = float(rec["top_y"]), float(rec["bottom_y"])
        poly = self.left.segments == 3 or self.right.segments == 3
        self.strips = _strip_bounds(self.left, self.right, self.top, self.bottom) if poly else [(self.top, self.bottom)]
        mats = [column_warp_matrix(page_w, self.left, self.right, a, b) for a, b in self.strips]
        self.out_w = max(m[1] for m in mats)
        self.mats = [column_warp_matrix(page_w, self.left, self.right, a, b, out_w=self.out_w) for a, b in self.strips]
        self.offs = [0]
        for m in self.mats:
            self.offs.append(self.offs[-1] + m[2])
        self.height = self.offs[-1]
        self.invs = [np.linalg.inv(m[0]) for m in self.mats]

    def row_to_page(self, r: float, u: float | None = None) -> tuple[float, float]:
        u = self.out_w / 2.0 if u is None else u
        i = max(0, min(len(self.strips) - 1, next((k for k in range(len(self.strips)) if r < self.offs[k + 1]), len(self.strips) - 1)))
        v = r - self.offs[i]
        p = self.invs[i] @ np.array([u, v, 1.0])
        return float(p[0] / p[2]), float(p[1] / p[2])

    def page_to_row(self, x: float, y: float) -> tuple[float, float]:
        i = max(0, min(len(self.strips) - 1, next((k for k, (a, b) in enumerate(self.strips) if y < b), len(self.strips) - 1)))
        p = self.mats[i][0] @ np.array([x, y, 1.0])
        return float(p[1] / p[2]) + self.offs[i], float(p[0] / p[2])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--workspace", default=r"D:\workspace\siku-zongmu-workspace")
    ap.add_argument("--shard", default=str(SHARD))
    ap.add_argument("--windows-bak", required=True, help="重跑前 column_warp 产物备份目录（旧几何）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-shift", type=float, default=120.0)
    a = ap.parse_args()
    ws = Path(a.workspace); shard = Path(a.shard)
    old_w = load_windows(Path(a.windows_bak))
    new_w = load_windows(ws / "products" / a.book / "column_warp")
    imgd = ws / "cache" / a.book / "column_image"

    lines = [json.loads(ln) for ln in shard.read_text(encoding="utf-8").splitlines() if ln.strip()]
    geoms: dict[tuple[int, int, str], Geom | None] = {}

    def geom(pg: int, col: int, which: str) -> Geom | None:
        key = (pg, col, which)
        if key not in geoms:
            src = old_w if which == "old" else new_w
            if pg not in src or col not in src[pg][1] or src[pg][0] is None:
                geoms[key] = None
            else:
                try:
                    geoms[key] = Geom(src[pg][1][col], src[pg][0])
                except Exception:
                    geoms[key] = None
        return geoms[key]

    todo, unchanged, skipped, too_big = [], 0, 0, []
    for o in lines:
        an = o.get("anchor", {})
        if an.get("book") != a.book:
            continue
        ex = o.get("expected", {})
        if "y" not in ex:
            continue
        pg, col = an["page"], an["col"]
        if pg not in old_w or pg not in new_w or col not in old_w[pg][1] or col not in new_w[pg][1]:
            skipped += 1
            continue
        ro, rn = old_w[pg][1][col], new_w[pg][1][col]
        if all(ro.get(k) == rn.get(k) for k in GEOM_KEYS):
            unchanged += 1
            continue
        go, gn = geom(pg, col, "old"), geom(pg, col, "new")
        if go is None or gn is None:
            skipped += 1
            continue
        x, y = go.row_to_page(float(ex["y"]))
        r_new, _ = gn.page_to_row(x, y)
        if abs(r_new - float(ex["y"])) > a.max_shift:
            too_big.append((o["id"], round(r_new - float(ex["y"]))))
            continue
        new_ex = {"y": r_new}
        if ex.get("y_old") is not None:
            xo, yo = go.row_to_page(float(ex["y_old"])); new_ex["y_old"] = gn.page_to_row(xo, yo)[0]
        if ex.get("polyline"):
            pl = []
            for px, py in ex["polyline"]:
                xx, yy = go.row_to_page(float(py), float(px)); rr, uu = gn.page_to_row(xx, yy)
                pl.append([round(uu, 1), round(rr, 1)])
            new_ex["polyline"] = pl
        img = cv2.imread(str(imgd / f"p{pg:04d}c{col:02d}.png"), cv2.IMREAD_GRAYSCALE)
        new_ex["col_h"] = int(img.shape[0]) if img is not None else int(gn.height)
        todo.append((o, new_ex, img))

    print(f"{a.book}: 列窗变了要重映射 {len(todo)} 条；列窗没变 {unchanged}；缺列窗/几何 {skipped}；"
          f"位移超 {a.max_shift:.0f}px 拒绝 {len(too_big)} {too_big[:6]}")
    better = worse = same = 0
    for o, new_ex, img in todo:
        if img is None:
            continue
        prof = (img < 128).mean(axis=1)
        yo, yn = int(round(o["expected"]["y"])), int(round(new_ex["y"]))
        io_ = float(prof[yo]) if 0 <= yo < len(prof) else -1.0
        inew = float(prof[yn]) if 0 <= yn < len(prof) else -1.0
        if inew < io_ - 0.005: better += 1
        elif inew > io_ + 0.005: worse += 1
        else: same += 1
    print(f"验（新列图上，旧行号 vs 新行号处的墨）：更干净 {better} / 更脏 {worse} / 不变 {same}")
    if not a.apply:
        print("（只看模式。加 --apply 写回）")
        return 0
    bak = shard.with_suffix(f".jsonl.bak-remap-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(shard, bak); print(f"已备份 → {bak}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for o, new_ex, _ in todo:
        ex = o["expected"]
        d = new_ex["y"] - float(ex["y"])
        ex.update(new_ex)
        o.setdefault("history", []).append({"change": "remap", "ts": now,
                                            "why": f"列窗几何变动，按射影矩阵重映射（Δy {d:+.0f}px，remap_cutline_gold.py）"})
    shard.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in lines) + "\n", encoding="utf-8")
    print(f"已写回 {len(todo)} 条 → {shard}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
