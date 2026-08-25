#!/usr/bin/env python3
"""调查脚本：boundary_ink 误报收敛（任务C）。

复放金标涉及页的 extract_page，捕获每个实例**裁紧前**的格框图块与
格界/邻格上下文，量以下候选判据在金标（clean vs contaminated/truncated）
上的 精确/召回/误报：

  C0 现行 boundary_ink > 0.025
  C1 分侧：max(top_frac, bot_frac) 扫阈值
  C2 越线墨：本格墨越出格线的比例（历史失败特征，复测刷新负结果）
  C3 邻格墨接近度定向：只有当「本格墨贴线」且「邻格墨也贴线」（缝隙
     塌掉，粘连/残余风险）才认该侧的边缘带墨——列级上下文，历史失败
     记录点名的方向
  C4 C0 ∧ C3：现行判据加邻格闸

用法：PYTHONPATH=. python scripts/research_boundary_ink.py \
        ../open-guji-dataset/char-segmentation/instances/expected.json
"""
import json, sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from open_guji_cv.clustering import extractor as E

BT = E.BINARY_THRESHOLD_PATCH


def replay_book_pages(book: str, pages: set[str]):
    """复放 extract_page，返回 {id: record}。

    record: patch(裁紧前), cell_top/cell_bot(patch 坐标), flags(现行),
            strip_binary, owner, cell_idx, strip_y0(条带里图块的 y0),
            local_cells(整列格界), col_key
    """
    out_dir = REPO / "output" / book
    src = E.CharExtractor._resolve_source_dir(out_dir)
    recs = {}
    extractor = E.CharExtractor()
    for page in sorted(pages):
        img_path = E.CharExtractor._find_page_image(src, page)
        gf = out_dir / "phase3_char_grid" / f"{page}_char_grid.json"
        if img_path is None or not gf.exists():
            continue
        img = E.imread(str(img_path))
        if img is None:
            continue
        grid = json.load(open(gf, encoding="utf-8"))

        # 复刻 extract_page 主循环，但捕获中间量（与 extractor.py 同步维护）
        page_img = img
        if page_img.ndim == 3:
            page_img = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)
        shear = float(grid.get("grid", {}).get("shear", 0.0) or 0.0)
        if shear:
            page_img = E._deshear(page_img, shear)
        img_h, img_w = page_img.shape[:2]
        for col in grid.get("columns", []):
            col_no = int(col["index"])
            left_x, right_x = float(col["left_x"]), float(col["right_x"])
            cells = [c for c in col.get("cells", []) if c.get("type") == "char"]
            if not cells:
                continue
            heights = [float(c["y_bottom"]) - float(c["y_top"]) for c in cells]
            cell_h_ref = float(np.median(heights))
            gl, gr = col.get("cell_left_x"), col.get("cell_right_x")
            if gl is None or gr is None:
                shrink = min((right_x - left_x) * 0.03, 4.0)
                gl, gr = left_x + shrink, right_x - shrink
            sx0 = int(round(max(0.0, float(gl))))
            sx1 = int(round(min(float(img_w), float(gr))))
            pad_y = cell_h_ref * extractor.padding_ratio
            sy0 = int(round(max(0.0, min(float(c["y_top"]) for c in cells) - pad_y)))
            sy1 = int(round(min(float(img_h),
                               max(float(c["y_bottom"]) for c in cells) + pad_y)))
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            strip = page_img[sy0:sy1, sx0:sx1]
            bands = col.get("cell_bands")
            if bands:
                strip = strip.copy()
                for ya, yb, blx, brx in bands:
                    ra = max(0, int(round(ya)) - sy0)
                    rb = min(strip.shape[0], int(round(yb)) - sy0)
                    if rb <= ra:
                        continue
                    ca = max(0, int(round(blx)) - sx0)
                    cb = min(strip.shape[1], int(round(brx)) - sx0)
                    if ca > 0:
                        strip[ra:rb, :ca] = 255
                    if cb < strip.shape[1]:
                        strip[ra:rb, cb:] = 255
            local = [(int(c["index"]), float(c["y_top"]) - sy0,
                      float(c["y_bottom"]) - sy0) for c in cells]
            strip = E.mask_frame_bars_outside(
                strip, local, int(round(left_x)) - sx0,
                int(round(right_x)) - sx0, cell_h_ref)
            boxes, owner = E._assign_column(strip, local, cell_h_ref,
                                            float(sx1 - sx0))
            for cell, (idx, ltop, lbot) in zip(cells, local):
                cell_h = lbot - ltop
                pad = cell_h * extractor.padding_ratio
                y0 = max(0, int(round(ltop - pad)))
                y1 = min(strip.shape[0], int(round(lbot + pad)))
                box = boxes.get(idx)
                if box is not None:
                    lim = cell_h * E.MAX_EXTEND_RATIO
                    y0 = max(0, int(round(max(ltop - lim, min(y0, box[1])))))
                    y1 = min(strip.shape[0],
                             int(round(min(lbot + lim, max(y1, box[3])))))
                if y1 <= y0:
                    continue
                patch = E.clean_patch(strip, owner, idx, y0, y1)
                patch = E.strip_rule_residue(patch, cell_h)
                patch = E.strip_speckle_band(patch, ltop - y0, lbot - y0)
                iid = f"{book}:{page}:{col_no}:{idx}"
                recs[iid] = dict(
                    patch=patch, cell_top=ltop - y0, cell_bot=lbot - y0,
                    flags=E._defect_flags(patch),
                    bi=E._boundary_ink_frac(patch),
                    owner=owner, strip=strip, cell_idx=idx, y0=y0, y1=y1,
                    local=local, cell_h=cell_h)
    return recs


def side_fracs(patch):
    b = patch < BT
    total = int(b.sum())
    if total == 0:
        return 0.0, 0.0
    band = max(2, int(b.shape[0] * E.BOUNDARY_BAND))
    return int(b[:band].sum()) / total, int(b[-band:].sum()) / total


def cross_line_frac(r):
    """本格墨越出格线（上/下取大）的比例。"""
    patch, ct, cb = r["patch"], r["cell_top"], r["cell_bot"]
    b = patch < BT
    total = int(b.sum())
    if total == 0:
        return 0.0
    a = int(b[:max(0, int(ct))].sum())
    c = int(b[int(cb):].sum())
    return max(a, c) / total


def neighbor_gap(r, side):
    """本格墨与邻格墨隔着格线的缝宽（px）。无邻/无墨 → 大数。

    在 strip/owner 坐标系里量：own = owner==idx+1，邻 = owner==邻 idx+1。
    """
    owner, idx, local = r["owner"], r["cell_idx"], r["local"]
    order = [i for i, _t, _b in local]
    pos = order.index(idx)
    if side == "top":
        if pos == 0:
            return 999
        nb = order[pos - 1]
        line = [t for i, t, _b in local if i == idx][0]
    else:
        if pos == len(order) - 1:
            return 999
        nb = order[pos + 1]
        line = [b for i, _t, b in local if i == idx][0]
    own_rows = np.flatnonzero((owner == idx + 1).any(axis=1))
    nb_rows = np.flatnonzero((owner == nb + 1).any(axis=1))
    if own_rows.size == 0 or nb_rows.size == 0:
        return 999
    if side == "top":
        own_edge = own_rows.min()
        nb_edge = nb_rows.max()
        return max(0, own_edge - nb_edge)
    own_edge = own_rows.max()
    nb_edge = nb_rows.min()
    return max(0, nb_edge - own_edge)


def main():
    gold = json.load(open(sys.argv[1], encoding="utf-8"))
    gold = [g for g in gold if g["quality"] in
            ("clean", "contaminated", "truncated")]
    by_book = defaultdict(set)
    for g in gold:
        by_book[g["book"]].add(g["page"])
    recs = {}
    for book, pages in by_book.items():
        recs.update(replay_book_pages(book, pages))
    rows = []
    for g in gold:
        iid = f"{g['book']}:{g['page']}:{g['col']}:{g['idx']}"
        r = recs.get(iid)
        if r is None:
            continue
        tf, bf = side_fracs(r["patch"])
        rows.append(dict(
            id=iid, quality=g["quality"], defect=g.get("defect"),
            seed=g.get("seed"), bi=round(r["bi"], 4),
            top=round(tf, 4), bot=round(bf, 4),
            cross=round(cross_line_frac(r), 4),
            gap_top=int(neighbor_gap(r, "top")),
            gap_bot=int(neighbor_gap(r, "bot")),
            flags=r["flags"]))
    json.dump(rows, open("/tmp/guji_taskC/features.json", "w"),
              ensure_ascii=False)
    print(f"matched {len(rows)}/{len(gold)}")
    print("saved /tmp/guji_taskC/features.json")

    # 队列体量对照：金标页上的**全部**实例的 (bi, top, bot)，落盘供离线扫阈值
    pop = {iid: (round(r["bi"], 4), *[round(v, 4) for v in side_fracs(r["patch"])])
           for iid, r in recs.items()}
    json.dump(pop, open("/tmp/guji_taskC/population.json", "w"))
    n = len(pop)
    n_bi = sum(1 for v in pop.values() if v[0] > E.BOUNDARY_INK_T)
    n_bot = sum(1 for v in pop.values() if v[2] > 0.01)
    print(f"金标页全部实例 n={n}: 现行 bi 标 {n_bi} ({100*n_bi/n:.1f}%), "
          f"bot>0.01 标 {n_bot} ({100*n_bot/n:.1f}%)")


if __name__ == "__main__":
    main()
