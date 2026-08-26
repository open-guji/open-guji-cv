"""右缘穿边救援回归（char-segmentation/right-cut）。

字压着界行写时，cell_right_x 贴界行内缘裁，捺脚/横尾被切断（2026-08-26
用户 r10：「有的整列从右边被剪切」）。金标 = 全书扫描出的穿边笔画组件
（从格内深处一直连到裁切边外，高 ≤30 排除界行、面积 ≥25 排除噪点），
每条记 (y, 墨尽头 extent)。

口径：现场重跑 extract_page（不读产物），穿边点所在格的图块外接框
右缘必须盖住 extent−2（笔尖救回来了）。找不到承载格的穿边点单列出
（多为格间隙里的邻格出头，人工过目）。

用法：PYTHONPATH=. python scripts/eval_right_cut.py <数据集目录>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    gold = json.loads((Path(args.dataset) / "right-cut" / "expected.json")
                      .read_text(encoding="utf-8"))["columns"]

    import cv2
    from open_guji_cv.clustering.extractor import CharExtractor

    ex = CharExtractor()
    pages = sorted({(e["book"], e["page"]) for e in gold})
    insts: dict[tuple, list] = {}
    for book, page in pages:
        gp = (Path(args.out) / book / "phase3_char_grid"
              / f"{page}_char_grid.json")
        img = cv2.imread(f"{args.out}/{book}/{page}.png")
        if img is None or not gp.exists():
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        for inst, _p in ex.extract_page(img, grid, book, page):
            if inst.sub or inst.cell_type != "char":
                continue
            insts.setdefault((book, page, inst.col), []).append(inst)

    n_ok = n_cut = n_orphan = 0
    for e in gold:
        rows = insts.get((e["book"], e["page"], e["col"]), [])
        for cr in e["crossings"]:
            y, ext = cr["y"], cr["extent"]
            host = [r for r in rows if r.bbox[1] - 2 <= y <= r.bbox[3] + 2]
            if not host:
                n_orphan += 1
                continue
            r = max(host, key=lambda r: r.bbox[2])
            if r.bbox[2] >= ext - 2:
                n_ok += 1
            else:
                n_cut += 1
                print(f"  ✗ 仍被剪 {e['book']}/{e['page']}:{e['col']} "
                      f"y={y} 墨到 {ext}，框到 {r.bbox[2]:.0f}")
    tot = n_ok + n_cut
    print(f"\nright-cut：穿边点 {tot + n_orphan}，救回 {n_ok}/{tot}"
          f"（{n_ok / tot:.0%}），无承载格 {n_orphan}（人工过目）")
    ok = n_cut <= tot * 0.1        # 允许 10% 疑难（弯钩/极端出头）
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
