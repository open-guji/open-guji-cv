"""从产物里挖「侧边界行残余」测试集分片（char-segmentation/side-rule）。

正样本：图块里有一条**完全落在文字带之外**的细高连通体（界行/版框残段）。
负样本：细高连通体落在**文字带之内**——那是字自己的竖笔（忄的左竖、
阝、川、而 的边竖），一根都不许剥。

基线 main_ink 取自当前产物的最大连通体墨量：剥离只动独立连通体，字身
不该少一个像素。part_ink 是负样本那条竖笔自己的墨量，用来验证它还在。

用法：PYTHONPATH=. python scripts/build_side_rule_shard.py \
        --pages vol01:4,18 vol02:115,171 --out <dataset>/char-segmentation/side-rule
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.extractor import (BINARY_THRESHOLD_PATCH,
                                               SIDE_RULE_ASPECT,
                                               SIDE_RULE_MAX_W,
                                               SIDE_RULE_MIN_AREA)


def side_candidates(img: np.ndarray, x0: float, text_x0: float,
                    text_x1: float) -> tuple[int, list[dict]]:
    """返回（字身墨量, 细高连通体清单）。清单项含 out=是否出文字带。"""
    binary = (img < BINARY_THRESHOLD_PATCH).astype(np.uint8)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(binary, 8)
    if n <= 1:
        return 0, []
    main = int(np.argmax(st[1:, 4])) + 1
    out = []
    for k in range(1, n):
        if k == main:
            continue
        cx, cw, ch, area = (int(st[k, 0]), int(st[k, 2]),
                            int(st[k, 3]), int(st[k, 4]))
        if area < SIDE_RULE_MIN_AREA or cw > SIDE_RULE_MAX_W:
            continue
        if ch < cw * SIDE_RULE_ASPECT:
            continue
        # 「出带」判中心，与 strip_side_rule 同口径（版框线常压在带边上）
        gc = x0 + cx + cw / 2.0
        out.append({"w": cw, "h": ch, "area": area,
                    "out": bool(gc < text_x0 or gc > text_x1)})
    return int(st[1:, 4].max()), out


def parse_pages(specs: list[str]) -> list[tuple[str, str]]:
    res = []
    for spec in specs:
        book, rng = spec.split(":")
        for part in rng.split(","):
            if "-" in part:
                a, b = part.split("-")
                res.extend((book, str(n)) for n in range(int(a), int(b) + 1))
            else:
                res.append((book, part))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--seed", default="review_r7")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    for book, page in parse_pages(args.pages):
        gp = Path("output") / book / "phase3_char_grid" / f"{page}_char_grid.json"
        if not gp.exists():
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        band = {int(c["index"]): (float(c["left_x"]), float(c["right_x"]))
                for c in grid.get("columns", [])}
        ip = Path("output") / book / "phase4_chars" / "index.jsonl"
        for line in ip.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["page"] != page or r["cell_type"] != "char" or r.get("sub"):
                continue
            if r["col"] not in band:
                continue
            img = cv2.imread(str(Path("output") / book / "phase4_chars"
                                 / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            tl, tr = band[r["col"]]
            main_ink, cands = side_candidates(img, float(r["bbox"][0]), tl, tr)
            if not cands:
                continue
            outs = [c for c in cands if c["out"]]
            ins = [c for c in cands if not c["out"]]
            rows.append({"book": book, "page": page, "col": r["col"],
                         "idx": r["idx"],
                         "side_rule": bool(outs),
                         "main_ink": main_ink,
                         "keep_ink": sum(c["area"] for c in ins),
                         "seed": args.seed, "label_origin": "human",
                         "schema_version": 1})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "expected.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    pos = sum(1 for r in rows if r["side_rule"])
    print(f"{len(rows)} 条（带界行残余 {pos} / 只有带内竖笔 {len(rows) - pos}）"
          f" → {out / 'expected.json'}")


if __name__ == "__main__":
    main()
