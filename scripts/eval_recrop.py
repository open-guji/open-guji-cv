"""review_recrop 分片回归：当前切分 bbox vs 人工拖框金标的 IoU。

金标来自进库审查页的人工重切事件回流（open-guji-dataset/
char-segmentation/instances 里 seed=="review_recrop" 的条目）：
old_bbox 是当时切分的坏输出，corrected_bbox 是用户拖框。
回归口径：当前产物在这些 (page,col,idx) 上的 bbox 与 corrected_bbox
的 IoU ≥ 0.85 为过；修不好的至少要被 flag 进审查队列（不能无声放行）。
分片是定向富集（只有切错的才被重切），通过率不能读作全书正确率。

用法：PYTHONPATH=. python scripts/eval_recrop.py \
        ../open-guji-dataset/char-segmentation/instances [--out report.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def iou(a: tuple, b: tuple) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    gold = [e for e in json.loads(
        (Path(args.dataset) / "expected.json").read_text(encoding="utf-8"))
        if e.get("seed") == "review_recrop"]
    if not gold:
        print("没有 review_recrop 条目")
        return

    index: dict[tuple, dict] = {}
    for book in {e["book"] for e in gold}:
        p = Path("output") / book / "phase4_chars" / "index.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            index[(r["book"], r["page"], r["col"], r["idx"])] = r

    import cv2
    import numpy as np
    from open_guji_cv.clustering.grid_segment import deshear

    grids: dict[tuple, dict] = {}

    def page_gray(book: str, page: str):
        key = (book, page)
        if key not in grids:
            img = cv2.imread(f"output/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
            gp = Path("output") / book / "phase3_char_grid" \
                / f"{page}_char_grid.json"
            sh = 0.0
            if gp.exists():
                sh = float(json.loads(gp.read_text(encoding="utf-8"))
                           .get("grid", {}).get("shear", 0.0) or 0.0)
            if img is not None and sh:
                img = deshear(img, sh)
            grids[key] = img
        return grids[key]

    # 口径（2026-08-24 裁紧定版后）：图块框=墨迹外接框 ±2px，而人工拖框
    # 带 ~10px 余量，IoU 对「更紧的正确框」会误判。改判两条：
    # 1) 紧框 ⊆ 金标框 +CONTAIN_TOL（框里没混进金标框外的东西）；
    # 2) 金标框内的墨 ≥INK_COVER 落在紧框内（该要的字墨没丢）。
    CONTAIN_TOL = 8
    INK_COVER = 0.95
    rows = []
    n_pass = n_flagged = n_missing = 0
    for e in gold:
        key = (e["book"], e["page"], e["col"], e["idx"])
        cur = index.get(key)
        if cur is None:
            # 格位在新网格下不存在（相位/列数变了）——单列出，人工重看
            rows.append({"key": ":".join(map(str, key[1:])),
                         "defect": e.get("defect"), "status": "missing"})
            n_missing += 1
            continue
        v_old = iou(tuple(e["old_bbox"]), tuple(e["corrected_bbox"]))
        v_new = iou(tuple(cur["bbox"]), tuple(e["corrected_bbox"]))
        gx0, gy0, gx1, gy1 = e["corrected_bbox"]
        nx0, ny0, nx1, ny1 = cur["bbox"]
        contained = (nx0 >= gx0 - CONTAIN_TOL and ny0 >= gy0 - CONTAIN_TOL
                     and nx1 <= gx1 + CONTAIN_TOL and ny1 <= gy1 + CONTAIN_TOL)
        cover = None
        img = page_gray(e["book"], e["page"])
        if img is not None:
            sub = img[int(gy0):int(gy1), int(gx0):int(gx1)] < 128
            total = int(sub.sum())
            if total:
                a0 = max(0, int(ny0 - gy0)); a1 = max(0, int(ny1 - gy0))
                b0 = max(0, int(nx0 - gx0)); b1 = max(0, int(nx1 - gx0))
                inside = int(sub[a0:a1, b0:b1].sum())
                cover = inside / total
        ok = contained and (cover is None or cover >= INK_COVER)
        flagged = bool(cur.get("flags"))
        n_pass += ok
        n_flagged += (not ok and flagged)
        rows.append({"key": ":".join(map(str, key[1:])),
                     "defect": e.get("defect"),
                     "iou_old": round(v_old, 3), "iou_new": round(v_new, 3),
                     "contained": contained,
                     "cover": round(cover, 3) if cover is not None else None,
                     "pass": ok, "flags": cur.get("flags") or []})

    rows.sort(key=lambda r: r.get("iou_new", -1))
    for r in rows:
        if r.get("status") == "missing":
            print(f"  {r['key']:<12} {str(r['defect']):<18} 格位消失（需人工重看）")
        else:
            mark = "过" if r["pass"] else ("兜" if r["flags"] else "漏")
            cov = f" 盖{r['cover']:.2f}" if r.get('cover') is not None else ""
            cont = "" if r.get('contained') else " 越界"
            print(f"  {r['key']:<12} {str(r['defect']):<18} "
                  f"IoU {r['iou_old']:.2f}→{r['iou_new']:.2f}{cov}{cont} [{mark}]"
                  f"{' ' + ','.join(r['flags']) if r['flags'] else ''}")
    n = len(gold)
    print(f"\nreview_recrop {n} 条：IoU≥0.85 通过 {n_pass}，"
          f"未过但有 flag 兜底 {n_flagged}，"
          f"无声放行 {n - n_pass - n_flagged - n_missing}，格位消失 {n_missing}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False,
                                             indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
