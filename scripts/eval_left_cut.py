"""左缘穿边救援回归（char-segmentation/left-cut）——right-cut 的镜像。

撇尖/横尾穿过左裁切边被切（右缘 r10 用户反馈的镜像病灶，全书扫描
74 列 130 点）。金标判据与右缘同款另加两道横条防线（宽 ≤45、不贴
探测窗左缘——横向栏线/中缝线也细着穿边，首版扫描近半是它们，废案
记分片 README）。

口径：现场重跑 extract_page（不读产物），穿边点所在格的图块外接框
左缘必须盖住 extent+2（笔尖救回来了）。找不到承载格的穿边点单列出。

用法：PYTHONPATH=. python scripts/eval_left_cut.py <数据集目录>

【2026-09-30 M1 C 组：默认改读现行 v2 链】
旧读法要 v1 `output/<册>/phase3_char_grid` + 整页 png（已退役，云端没有 → 穿边点全部成「无承载格」，
且 n_ok+n_cut=0 时 `n_ok / tot` 直接 ZeroDivisionError）。v2 口径：
  - 金标读 `left-cut/expected_v2.json`（`artifacts/m1_gold/left_cut/scan_cut_crossings_v2.py` 在 v2 列图上按**同一条
    纯墨迹判据**重扫，坐标=列图、列号右起 1；旧 v1 金标整体失效，见 MIGRATION.md）；
  - 被测框读 v2 `cell_shrink` 产物的 `bbox_col`，承载格 = 非夹注半格、`cell_type=="char"`、y 区间含穿边点 ±2；
  - 判定不变：框左缘 ≤ extent+2。
指标名（救回 n_ok/tot、无承载格、回归门 ≤10% 仍被剪）一字未动。`--v1` 保留旧读法。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_v2(gold):
    """{(book,page,col): [(y0, y1, x0, x1)]}——v2 非夹注半格的 char 紧框（列图坐标）。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _v2_step4 import V2Book

    class R:
        def __init__(self, b):
            self.bbox = b

    insts: dict[tuple, list] = {}
    by: dict[str, set] = {}
    for e in gold:
        by.setdefault(e["book"], set()).add(int(e["page"]))
    for book, pgs in by.items():
        v = V2Book(book)
        v.ensure(pgs)
        for pg in pgs:
            pc = v.chars(pg)
            if pc is None:
                continue
            for cc in pc.columns:
                if not cc.ok:
                    continue
                rows = [R(tuple(r.bbox_col)) for r in cc.chars if not r.sub and r.cell_type == "char"]
                insts[(book, str(pg), cc.col)] = rows
    return insts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--v1", action="store_true", help="旧读法（v1 phase3_char_grid，已退役）")
    args = ap.parse_args()
    gold = json.loads((Path(args.dataset) / "left-cut" / ("expected.json" if args.v1 else "expected_v2.json"))
                      .read_text(encoding="utf-8"))["columns"]

    insts: dict[tuple, list] = {}
    if not args.v1:
        insts = load_v2(gold)
    else:
        import cv2
        from open_guji_cv.clustering.extractor import CharExtractor
        ex = CharExtractor()
    pages = sorted({(e["book"], e["page"]) for e in gold}) if args.v1 else []
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
            r = min(host, key=lambda r: r.bbox[0])
            if r.bbox[0] <= ext + 2:
                n_ok += 1
            else:
                n_cut += 1
                print(f"  ✗ 仍被剪 {e['book']}/{e['page']}:{e['col']} "
                      f"y={y} 墨到 {ext}，框到 {r.bbox[0]:.0f}")
    tot = n_ok + n_cut
    if tot == 0:
        print(f"\nleft-cut：穿边点 {n_orphan}，可评 0（无承载格 {n_orphan}）——空跑，不算通过")
        print("回归门：**失败**")
        raise SystemExit(1)
    print(f"\nleft-cut：穿边点 {tot + n_orphan}，救回 {n_ok}/{tot}"
          f"（{n_ok / tot:.0%}），无承载格 {n_orphan}（人工过目）")
    ok = n_cut <= tot * 0.1        # 与右缘同：允许 10% 疑难
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
