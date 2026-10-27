"""自由版式管线（keben_free）产物叠图：块（红框）、列缝（灰）、字框（按种类着色）、块的列数。

    python research/free_layout/overlay.py <工作区> <册> <页,页,…> <输出目录> [--scale 0.5]

只读产物，不跑算法。颜色：大字 红，双行小注右线 绿、左线 蓝，单行小注 紫。
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

COLORS = {"char": (0, 0, 255), "jiazhu_a": (0, 150, 0), "jiazhu_b": (255, 0, 0), "jiazhu_solo": (200, 0, 200)}


def load(ws: Path, book: str, step: str, kind: str, page: int):
    f = ws / "products" / book / step / f"p{page:04d}.json"
    return json.loads(f.read_text())[kind] if f.exists() else None


def tl(x, W):
    return int(round(W - 1 - x))


def draw(ws: Path, book: str, page: int, raw: Path, scale: float) -> np.ndarray:
    g = cv2.imread(str(raw), cv2.IMREAD_GRAYSCALE)
    H, W = g.shape
    ov = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    lb = load(ws, book, "block_detect", "layout_blocks", page)
    fc = load(ws, book, "column_trace", "free_columns", page)
    ce = load(ws, book, "cell_cut", "free_cells", page)
    if lb and lb["page_type"] == "skip":
        cv2.putText(ov, "SKIP", (60, 200), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 255), 8)
    for b in (lb or {}).get("blocks", []):
        x0, y0, x1, y1 = b["box"]
        col = (0, 0, 255) if b["kind"] == "text" else (128, 128, 128)
        cv2.rectangle(ov, (tl(x1, W), int(y0)), (tl(x0, W), int(y1)), col, 6)
    for c in (fc or {}).get("columns", []):
        h = int(c["y1"] - c["y0"])
        ys = np.r_[np.arange(0, h, c["step"]), h - 1][:len(c["right"])] + c["y0"]
        for side in ("right", "left"):
            pts = np.stack([[tl(x, W) for x in c[side]], ys], 1).astype(np.int32)
            cv2.polylines(ov, [pts], False, (150, 150, 150), 2)
        cv2.putText(ov, str(c["col"]), (tl(c["right"][0], W) - 40, int(c["y0"]) + 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 200), 3)
    for x in (ce or {}).get("cells", []):
        x0, y0, x1, y1 = x["box"]
        cv2.rectangle(ov, (tl(x1, W), int(y0)), (tl(x0, W), int(y1)), COLORS.get(x["kind"], (0, 0, 0)), 3)
    info = " ".join(f"b{b['block']}:{b['n']}{'' if b['n_source'] == 'auto' else '(' + b['n_source'] + ')'}"
                    for b in (fc or {}).get("blocks", []))
    cv2.putText(ov, f"p{page} {info}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255), 4)
    return cv2.resize(ov, None, fx=scale, fy=scale)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("book")
    ap.add_argument("pages")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--raw", default=None, help="原图目录（缺省 <工作区>/data_full/<册>）")
    a = ap.parse_args()
    ws = Path(a.ws)
    raw = Path(a.raw) if a.raw else ws / "data_full" / a.book
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for s in a.pages.split(","):
        p = int(s)
        cv2.imwrite(str(out / f"p{p:03d}.jpg"), draw(ws, a.book, p, raw / f"{p}.png", a.scale),
                    [cv2.IMWRITE_JPEG_QUALITY, 80])


if __name__ == "__main__":
    main()
