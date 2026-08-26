"""把自评样本渲染成判读表：〔语境图（红框=紧裁框）｜成品图块〕。

判读只看这两样：语境图回答「这个框圈的是不是**恰好一个整字**」，
成品图块回答「下游拿到的是什么」。两者并排才判得动——只看图块看不出
少了偏旁，只看语境看不出后处理把什么抹了。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.grid_segment import deshear

PAD = 28
TILE_H = 190
MAX_W = 240      # 单块限宽：「一」这类扁字的语境图能宽到 5 倍，
                 # 不限宽的话整张表的列宽被它撑爆、其余格小到看不清
COLS = 4
ROWS = 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--stratum", default="rand")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = [r for r in json.loads(Path(a.sample).read_text(encoding="utf-8"))
            if r["stratum"] == a.stratum]
    rows.sort(key=lambda r: (r["book"], int(r["page"]), r["col"], r["idx"]))
    outd = Path(a.out)
    outd.mkdir(parents=True, exist_ok=True)

    pages: dict[tuple, np.ndarray] = {}

    def page_img(book: str, page: str) -> np.ndarray | None:
        k = (book, page)
        if k not in pages:
            img = cv2.imread(f"output/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
            if img is not None:
                gp = Path(f"output/{book}/phase3_char_grid/{page}_char_grid.json")
                sh = 0.0
                if gp.exists():
                    sh = float(json.loads(gp.read_text(encoding="utf-8"))
                               .get("grid", {}).get("shear", 0.0) or 0.0)
                if sh:
                    img = deshear(img, sh)
            pages[k] = img
        return pages[k]

    def tile(r: dict) -> np.ndarray:
        img = page_img(r["book"], r["page"])
        x0, y0, x1, y1 = [int(round(v)) for v in r["bbox"]]
        if img is None:
            ctx = np.full((TILE_H, TILE_H, 3), 200, np.uint8)
        else:
            H, W = img.shape
            cx0, cy0 = max(0, x0 - PAD), max(0, y0 - PAD)
            cx1, cy1 = min(W, x1 + PAD), min(H, y1 + PAD)
            c = cv2.cvtColor(img[cy0:cy1, cx0:cx1], cv2.COLOR_GRAY2BGR)
            cv2.rectangle(c, (x0 - cx0, y0 - cy0), (x1 - cx0 - 1, y1 - cy0 - 1),
                          (0, 0, 255), 1)
            s = min(TILE_H / max(1, c.shape[0]), MAX_W / max(1, c.shape[1]))
            ctx = cv2.resize(c, (max(1, int(c.shape[1] * s)),
                                 max(1, int(c.shape[0] * s))))
            if ctx.shape[0] < TILE_H:      # 顶部对齐，下方留白
                ctx = cv2.copyMakeBorder(ctx, 0, TILE_H - ctx.shape[0], 0, 0,
                                         cv2.BORDER_CONSTANT, value=(245,245,245))
        p = cv2.imread(f"output/{r['book']}/phase4_chars/{r['patch_path']}",
                       cv2.IMREAD_GRAYSCALE)
        if p is None:
            pat = np.full((TILE_H, 60, 3), 230, np.uint8)
        else:
            s = min(TILE_H / max(1, p.shape[0]), MAX_W / max(1, p.shape[1]))
            pat = cv2.cvtColor(
                cv2.resize(p, (max(1, int(p.shape[1] * s)),
                               max(1, int(p.shape[0] * s)))),
                cv2.COLOR_GRAY2BGR)
            if pat.shape[0] < TILE_H:
                pat = cv2.copyMakeBorder(pat, 0, TILE_H - pat.shape[0], 0, 0,
                                         cv2.BORDER_CONSTANT, value=(245,245,245))
        gap = np.full((TILE_H, 6, 3), 150, np.uint8)
        body = np.hstack([ctx, gap, pat])
        lab = np.full((22, body.shape[1], 3), 255, np.uint8)
        tag = f"{r['book'][3:]}/{r['page']}:{r['col']}:{r['idx']}{r.get('sub') or ''}"
        if r["flags"]:
            tag += " [" + ",".join(r["flags"])[:22] + "]"
        cv2.putText(lab, tag, (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, 0, 1)
        return np.vstack([lab, body])

    per = COLS * ROWS
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        tiles = [tile(r) for r in chunk]
        w = max(t.shape[1] for t in tiles) + 8
        h = max(t.shape[0] for t in tiles) + 8
        sheet = np.full((h * ROWS, w * COLS, 3), 245, np.uint8)
        for i, t in enumerate(tiles):
            rr, cc = divmod(i, COLS)
            sheet[rr * h:rr * h + t.shape[0], cc * w:cc * w + t.shape[1]] = t
        f = outd / f"{a.stratum}_{s // per + 1:02d}.png"
        cv2.imwrite(str(f), sheet)
    print(f"{a.stratum} {len(rows)} 格 → {outd} 共 {(len(rows)+per-1)//per} 张")


if __name__ == "__main__":
    main()
