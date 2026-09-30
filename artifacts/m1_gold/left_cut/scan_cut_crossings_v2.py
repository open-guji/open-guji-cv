# -*- coding: utf-8 -*-
"""left-cut / right-cut 金标在 v2 链上重扫（M1 道 C 组，2026-09-30）。

为什么是「重扫」不是「迁移」：
  旧金标是 v1 页图坐标系里的（y, extent, cell_left_x/cell_right_x），没有保存人裁图、也没有任何图像指纹；
  它本来就不是人标的——是按一条**纯墨迹判据**全书机扫出来的穿边笔画（README：「全书正文页扫描出的穿边笔画组件」）。
  v1 页图坐标系（v1 去斜页）与 v2 列图坐标系之间没有保存下来的映射，旧条目没法逐条定位到 v2 格，
  所以旧条目全部标「已失效（v1 页图坐标，无图像凭证）」，同一判据在 v2 列图上重扫，重冻「新口径首个基线」。
  旧值（救回 166/175=95% / 88/97=91%）只作趋势对照。

判据（与分片 README 一字对应，常数直接 import 生产代码，不另抄）：
  连通体从裁切边**外** ≥OUT px 连进格内 ≥IN px；高 ≤30；面积 ≥25；
  左缘另加：宽 ≤45 且不贴探测窗左缘；离列图上下端 >12px（列图已清版框，这条只防端部残渣）。
  右缘**不**加「不贴窗左缘」：试过镜像左缘防线，右缘点数 42→11（真笔画里长横/捺脚本来就会从窗左缘一路伸过来，
  如「一」「大」），把真对象杀掉了——v1 右缘金标也没有这条（README），保持口径。代价：列尾偶有贯穿的横向残段
  混进来（vol01/153:7 y=2424），如实留在基线里当「仍被剪」。
  用户排除页（vol02/3 污渍页、vol01/89/90、vol02/159/160 压缩职名页，2026-08-25 定「不判读、不入测试集」）不扫。
  裁切边 = v2 Step3 的 `content_x`（cell_shrink 喂给 CharExtractor 的 cell_left_x / cell_right_x）。
  坐标 = 列图坐标（左上原点，x 向右，y 向下）；列号 = v2 列号（右起 1）。

用法：python artifacts/m1_gold/left_cut/scan_cut_crossings_v2.py [--apply] [--pages vol01:5,6 ...]
  不带 --apply 只打印；--apply 写 `left-cut/expected_v2.json` 与 `right-cut/expected_v2.json`。
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
from _v2_step4 import V2Book, dataset_root  # noqa: E402
from open_guji_cv.clustering import extractor as X  # noqa: E402

END_MARGIN = 12
EXCLUDED = {("vol01", 89), ("vol01", 90), ("vol02", 3), ("vol02", 159), ("vol02", 160)}


def crossings_right(img: np.ndarray, sx1: int):
    H, W = img.shape
    if sx1 + X.RIGHT_RESCUE_OUT >= W:
        return []
    a, b = max(0, sx1 - 40), min(W, sx1 + X.RIGHT_RESCUE_MAX + 2)
    zone = (img[:, a:b] < X.BINARY_THRESHOLD_PATCH).astype(np.uint8)
    fence = sx1 - a
    n, _lab, st, _c = cv2.connectedComponentsWithStats(zone, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = (int(v) for v in st[k])
        if h > X.RIGHT_RESCUE_H or area < X.RIGHT_RESCUE_AREA:
            continue
        if x <= fence - X.RIGHT_RESCUE_IN and x + w >= fence + X.RIGHT_RESCUE_OUT:
            cy = y + h // 2
            if END_MARGIN < cy < H - END_MARGIN:
                out.append({"y": int(cy), "extent": int(a + x + w + 1)})
    return sorted(out, key=lambda d: d["y"])


def crossings_left(img: np.ndarray, sx0: int):
    H, W = img.shape
    if sx0 - X.RIGHT_RESCUE_OUT <= 0:
        return []
    a, b = max(0, sx0 - X.LEFT_RESCUE_MAX - 2), min(W, sx0 + 40)
    zone = (img[:, a:b] < X.BINARY_THRESHOLD_PATCH).astype(np.uint8)
    fence = sx0 - a
    n, _lab, st, _c = cv2.connectedComponentsWithStats(zone, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = (int(v) for v in st[k])
        if (h > X.RIGHT_RESCUE_H or area < X.RIGHT_RESCUE_AREA
                or w > X.LEFT_RESCUE_W or x <= 0):
            continue
        if x <= fence - X.RIGHT_RESCUE_OUT and x + w >= fence + X.RIGHT_RESCUE_IN:
            cy = y + h // 2
            if END_MARGIN < cy < H - END_MARGIN:
                out.append({"y": int(cy), "extent": int(a + x)})
    return sorted(out, key=lambda d: d["y"])


def body_pages(ds: Path):
    rows = json.loads((ds / "page-type" / "expected.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("pages", [])
    by: dict[str, list[int]] = {}
    for e in rows:
        if (e.get("page_type") == "body" and e["book"] in ("vol01", "vol02")
                and (e["book"], int(e["page"])) not in EXCLUDED):
            by.setdefault(e["book"], []).append(int(e["page"]))
    return {b: sorted(p) for b, p in by.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(dataset_root()))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pages", nargs="*", help="调试：book:1,2,3（只扫这些页，且不许 --apply）")
    a = ap.parse_args()
    ds = Path(a.dataset)
    pages = body_pages(ds)
    if a.pages:
        assert not a.apply, "--pages 只用于调试"
        pages = {s.split(":")[0]: [int(x) for x in s.split(":")[1].split(",")] for s in a.pages}
    L, R = [], []
    n_cols = 0
    scanned = 0
    skipped = []
    for book, pgs in pages.items():
        v = V2Book(book)
        v.ensure(pgs)
        for pg in pgs:
            cells = v.cells(pg)
            if cells is None or v.chars(pg) is None:
                skipped.append((book, pg))
                continue
            scanned += 1
            for cc in cells.columns:
                if not cc.ok or not cc.content_x:
                    continue
                n_cols += 1
                img = v.col_img(pg, cc.col)
                x0, x1 = int(round(cc.content_x[0])), int(round(cc.content_x[1]))
                cl, cr = crossings_left(img, x0), crossings_right(img, x1)
                if cl:
                    L.append({"book": book, "page": str(pg), "col": cc.col, "cell_left_x": x0, "crossings": cl})
                if cr:
                    R.append({"book": book, "page": str(pg), "col": cc.col, "cell_right_x": x1, "crossings": cr})
    nl = sum(len(e["crossings"]) for e in L)
    nr = sum(len(e["crossings"]) for e in R)
    print(f"扫 {scanned} 页 {n_cols} 列（无 v2 产物 {len(skipped)} 页 {skipped[:8]}）")
    print(f"left : {len(L)} 列 {nl} 点    right: {len(R)} 列 {nr} 点")
    if a.apply:
        note = ("2026-09-30 M1 C 组：v2 列图上按同一纯墨迹判据重扫，新口径首个基线；坐标=列图（左上原点）、列号右起 1；"
                "旧 v1 金标整体失效，见 artifacts/m1_gold/{left_cut,right_cut}/MIGRATION.md")
        for name, cols in (("left-cut", L), ("right-cut", R)):
            doc = {"note": note, "chain": "v2 (column_warp 列图 + row_segment + cell_shrink)", "columns": cols}
            (ds / "char-segmentation" / name / "expected_v2.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print("写入", ds / "char-segmentation" / name / "expected_v2.json")


if __name__ == "__main__":
    main()
