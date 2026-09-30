# -*- coding: utf-8 -*-
"""recrop 金标迁移到现行 v2 链（M1 道 C 组，2026-09-30）。

源：`open-guji-dataset/char-segmentation/instances/expected.json` 里 seed=="review_recrop" 的 40 条
    （人在 v1 页图坐标系里整格拖出 corrected_bbox；old_bbox 是当时的坏输出）。
目标：`instances/recrop_v2.json`——corrected_bbox / old_bbox 换算进**原图坐标**（raw_page_px@top-right），
    并锚到 v2 的 (col, slot)；迁不了的写进 `retired`，带原因。

判据——**只看图像，不用算法一致性**（算法一致性是循环论证）：

1. 框架证据（这批坐标系到底是不是这张页图的）：
   工作区 `output/<册>/<页>.png` 是 v1 页图（原图平移+去斜后的裁剪，仍在）。
   人裁图块 `instances/patches/<册>_<页>_<列>_<idx>.png` 是「人当时看的图」的现成证据：
     - 图块尺寸 == old_bbox 尺寸（整块就是 old_bbox 的裁片）且在页图 old_bbox 处找得到（NCC≥0.80、偏移≤8px）→ 精确证据；
     - 否则（图块是后来刷新的紧框）要求它落在 old∪corrected 外扩 16px 的范围里（NCC≥0.80）→ 旁证。
   一页里只要有一条证据成立，这页的页图坐标系就算与金标一致（页图是每页一张，不是每条一张）。
   整页没有任何证据 / 证据互相矛盾（偏移>8px）的页：整页失效。
2. 定位证据（人当时看的那块页图，能不能在现行原图里找回来）：
   取 old∪corrected 外扩 30px 那块页图（高斯模糊 σ=2，抗去斜后亚像素错位），
   在原图上（全局平移先验 ±50px 内）做归一化互相关；NCC≥0.85 才算找到，换算偏移取局部峰。
   找不到（NCC<0.85）→ 失效。
3. 格位锚：corrected_bbox（原图坐标）与 v2 Step3 格（row_segment.cells 的 quad_page 外接框）取 IoU 最大者，
   IoU≥0.30 才锚；锚不上 → 失效（v2 在这里没有这个格位）。

用法：python artifacts/m1_gold/recrop/migrate_recrop.py [--dataset ../open-guji-dataset] [--apply]
  不带 --apply 只打印；带 --apply 才写 instances/recrop_v2.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from _v2_step4 import V2Book, dataset_root, iou, tl2tr, tr2tl, workspace_output_dir  # noqa: E402

NCC_PATCH = 0.80         # 人裁图块在页图里的定位
SHIFT_MAX = 8            # 图块与 old_bbox 同尺寸时，允许的位置偏差
NCC_REG = 0.85           # 页图 → 原图 局部配准
CELL_IOU = 0.30          # 金标框 ↔ v2 格


def blur(g):
    return cv2.GaussianBlur(g, (0, 0), 2.0)


def global_offset(frame_b, scan_b):
    """页图在原图里的整体平移先验（取页图中部 400×400 做模板）。"""
    h, w = frame_b.shape
    best = (-1.0, (0, 0))
    for cy in (h // 2, h // 3, 2 * h // 3):
        for cx in (w // 2, w // 3, 2 * w // 3):
            y0, x0 = max(0, cy - 200), max(0, cx - 200)
            t = frame_b[y0:y0 + 400, x0:x0 + 400]
            r = cv2.matchTemplate(scan_b, t, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            if mx > best[0]:
                best = (mx, (loc[0] - x0, loc[1] - y0))
    return best[1], best[0]


def local_register(frame_b, scan_b, u, g, R=50):
    x0 = max(0, u[0] + g[0] - R)
    y0 = max(0, u[1] + g[1] - R)
    x1 = min(scan_b.shape[1], u[2] + g[0] + R)
    y1 = min(scan_b.shape[0], u[3] + g[1] + R)
    t = frame_b[u[1]:u[3], u[0]:u[2]]
    reg = scan_b[y0:y1, x0:x1]
    if reg.shape[0] < t.shape[0] or reg.shape[1] < t.shape[1]:
        return None
    r = cv2.matchTemplate(reg, t, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return (x0 + loc[0] - u[0], y0 + loc[1] - u[1]), float(mx)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(dataset_root()))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ds = Path(a.dataset) / "char-segmentation" / "instances"
    gold = [e for e in json.loads((ds / "expected.json").read_text(encoding="utf-8"))
            if e.get("seed") == "review_recrop"]
    out_dir = workspace_output_dir()
    assert out_dir is not None, "找不到工作区 output/（v1 页图）"

    # ── 1. 逐条：页图证据 + 配准 ─────────────────────────────────────
    rows = []
    frames: dict = {}
    for e in gold:
        b, pg = e["book"], int(e["page"])
        if (b, pg) not in frames:
            f = cv2.imread(str(out_dir / b / f"{pg}.png"), 0)
            v = V2Book(b)
            s = v.scan(pg)
            fb, sb = (blur(f), blur(s)) if f is not None else (None, None)
            g, gn = global_offset(fb, sb) if f is not None else ((0, 0), 0.0)
            frames[(b, pg)] = dict(f=f, s=s, fb=fb, sb=sb, g=g, gn=gn, v=v)
        F = frames[(b, pg)]
        row = {"id": f"{b}:{pg}:{e['col']}:{e['idx']}", "book": b, "page": pg, "v1_col": e["col"], "v1_idx": e["idx"],
               "defect": e.get("defect"), "old_bbox_v1": e["old_bbox"], "corrected_bbox_v1": e["corrected_bbox"]}
        if F["f"] is None:
            row.update(status="invalid", reason="v1 页图缺失")
            rows.append(row)
            continue
        ob, cb = e["old_bbox"], e["corrected_bbox"]
        pp = ds / "patches" / f"{b}_{pg}_{e['col']}_{e['idx']}.png"
        p = cv2.imread(str(pp), 0) if pp.exists() else None
        ev = {"patch": None}
        if p is not None:
            r = cv2.matchTemplate(F["f"], p, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            pb = [loc[0], loc[1], loc[0] + p.shape[1], loc[1] + p.shape[0]]
            same = (p.shape[1], p.shape[0]) == (int(round(ob[2] - ob[0])), int(round(ob[3] - ob[1])))
            sh = (loc[0] - ob[0], loc[1] - ob[1])
            un = [min(ob[0], cb[0]) - 16, min(ob[1], cb[1]) - 16, max(ob[2], cb[2]) + 16, max(ob[3], cb[3]) + 16]
            inside = pb[0] >= un[0] and pb[1] >= un[1] and pb[2] <= un[2] and pb[3] <= un[3]
            if same:
                kind = "exact" if (mx >= NCC_PATCH and max(abs(sh[0]), abs(sh[1])) <= SHIFT_MAX) else "conflict"
            else:
                kind = "nearby" if (mx >= NCC_PATCH and inside) else "none"
            ev["patch"] = {"kind": kind, "ncc": round(float(mx), 3), "shape_equals_old": bool(same),
                           "shift_vs_old": [int(sh[0]), int(sh[1])]}
        row["evidence"] = ev
        # 配准
        u = [min(ob[0], cb[0]) - 30, min(ob[1], cb[1]) - 30, max(ob[2], cb[2]) + 30, max(ob[3], cb[3]) + 30]
        u = [max(0, int(u[0])), max(0, int(u[1])), min(F["f"].shape[1], int(u[2])), min(F["f"].shape[0], int(u[3]))]
        reg = local_register(F["fb"], F["sb"], u, F["g"])
        if reg is None:
            row.update(status="invalid", reason="配准窗口越出原图")
            rows.append(row)
            continue
        (ox, oy), ncc = reg
        row["register"] = {"offset_frame_to_scan": [int(ox), int(oy)], "ncc": round(ncc, 3),
                           "global_offset": list(F["g"]), "global_ncc": round(F["gn"], 3)}
        rows.append(row)

    # ── 2. 页级框架证据 ──────────────────────────────────────────────
    by_page: dict = {}
    for r in rows:
        k = r["evidence"]["patch"]["kind"] if r.get("evidence") and r["evidence"]["patch"] else None
        by_page.setdefault((r["book"], r["page"]), []).append(k)
    page_ok = {}
    for k, kinds in by_page.items():
        good = sum(1 for x in kinds if x in ("exact", "nearby"))
        bad = sum(1 for x in kinds if x == "conflict")
        page_ok[k] = (good >= 1 and bad == 0)
    # ── 3. 格位锚 + 收口 ─────────────────────────────────────────────
    for r in rows:
        if r.get("status"):
            continue
        b, pg = r["book"], r["page"]
        F = frames[(b, pg)]
        k = (b, pg)
        if not page_ok[k]:
            kinds = by_page[k]
            r.update(status="invalid",
                     reason=("页图坐标系无图像凭证：本页人裁图块证据 " + str(kinds) +
                             "（需 ≥1 条 exact/nearby 且无 conflict）"))
            continue
        if r["register"]["ncc"] < NCC_REG:
            r.update(status="invalid", reason=f"人当时看的页图在现行原图里定位不上（NCC {r['register']['ncc']} < {NCC_REG}）")
            continue
        ox, oy = r["register"]["offset_frame_to_scan"]
        W = F["s"].shape[1]

        def shift(bb):
            return [bb[0] + ox, bb[1] + oy, bb[2] + ox, bb[3] + oy]
        cs, os_ = shift(r["corrected_bbox_v1"]), shift(r["old_bbox_v1"])
        v: V2Book = F["v"]
        miss = v.ensure([pg])
        cells = v.cells(pg)
        best = (0.0, None, None)
        if cells is not None:
            for cc in cells.columns:
                if not cc.ok:
                    continue
                for c in cc.cells:
                    if c.sub or not c.quad_page:
                        continue
                    xs = [q[0] for q in c.quad_page]
                    ys = [q[1] for q in c.quad_page]
                    box_tl = tr2tl((min(xs), min(ys), max(xs), max(ys)), W)
                    i = iou(cs, box_tl)
                    if i > best[0]:
                        best = (i, cc.col, c.slot)
        if best[1] is None or best[0] < CELL_IOU:
            r.update(status="invalid", reason=f"v2 Step3 没有对应格位（最佳 IoU {best[0]:.2f} < {CELL_IOU}）"
                     + ("；本页 v2 产物缺失" if miss else ""))
            continue
        r.update(status="migrated", col=best[1], slot=best[2], cell_iou=round(best[0], 3),
                 corrected_bbox=[round(x, 1) for x in tl2tr(cs, W)],
                 old_bbox=[round(x, 1) for x in tl2tr(os_, W)], space="raw_page_px@top-right")

    mig = [r for r in rows if r["status"] == "migrated"]
    bad = [r for r in rows if r["status"] != "migrated"]
    print(f"review_recrop 原 {len(rows)} 条：迁移 {len(mig)}，失效 {len(bad)}")
    from collections import Counter
    print("失效原因：", dict(Counter(r["reason"].split("（")[0].split("：")[0] for r in bad)))
    for r in rows:
        ncc = r.get("register", {}).get("ncc")
        print(f"  {r['id']:<18} {r['status']:<9} patch={r['evidence']['patch']['kind'] if r.get('evidence') and r['evidence']['patch'] else None!s:<8}"
              f" reg_ncc={ncc} " + (f"→ c{r['col']}s{r['slot']} iou={r['cell_iou']}" if r['status'] == 'migrated' else r['reason']))
    if a.apply:
        doc = {"schema": 1, "space": "raw_page_px@top-right",
               "note": "M1 C 组 2026-09-30 迁移：review_recrop 金标换算进原图坐标并锚到 v2 (col,slot)。判据见 "
                       "artifacts/m1_gold/recrop/MIGRATION.md",
               "items": mig, "retired": bad}
        (ds / "recrop_v2.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("写入", ds / "recrop_v2.json")


if __name__ == "__main__":
    main()
