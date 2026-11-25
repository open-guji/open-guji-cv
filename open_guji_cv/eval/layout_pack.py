"""标注包：把「现役算法的版面草稿」连图打成一个文件夹，交给网页标注工具
（open-guji-dataset `layout/tools/annotate.html`）。A21，2026-11-23。

    python -m open_guji_cv.eval.layout_pack --products <产物根> --workspace-raw <原图目录根> \
        --pick picks.json --out pack_dir --pack-id dian-r1 --source-rev 5

picks.json：`[{"book": "vol01", "page": 100, "stratum": "keben-body|cols10", "hint": "…", "split": "dev"}, …]`
原图路径 `<raw_root>/<册>/<页>.png`。输出：`pack.json`、`drafts.json`（每页一个 LayoutDoc 草稿，
折线已用 Douglas–Peucker 简化到 ≤1px 误差，点少好拖）、页图拷贝。
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from . import layout_bench as lb


def rdp(pts: list[list[float]], eps: float) -> list[list[float]]:
    """Douglas–Peucker 折线简化。"""
    a = np.asarray(pts, dtype=float)
    if len(a) <= 2:
        return [list(map(float, p)) for p in a]
    keep = np.zeros(len(a), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(a) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p, q = a[i], a[j]
        d = q - p
        n = np.hypot(*d) or 1.0
        dist = np.abs(d[0] * (a[i + 1:j, 1] - p[1]) - d[1] * (a[i + 1:j, 0] - p[0])) / n
        k = int(np.argmax(dist))
        if dist[k] > eps:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return [[round(float(x), 1), round(float(y), 1)] for x, y in a[keep]]


def simplify_doc(doc: dict, eps: float = 1.0) -> dict:
    for v in doc.get("vlines", []):
        v["pts"] = rdp(v["pts"], eps)
    for k in ("top", "bottom"):
        if doc.get(k):
            doc[k]["pts"] = rdp(doc[k]["pts"], eps)
    return doc


def build(products: Path, raw_root: Path, picks: list[dict], out: Path, pack_id: str,
          source_rev: int | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    drafts, pages, miss = {}, [], []
    book = picks[0]["book"] if picks else None
    for pk in picks:
        b, p = pk["book"], int(pk["page"])
        doc = lb.pred_doc(products, b, p)
        src = raw_root / b / f"{p}.png"
        if doc is None or not src.exists():
            miss.append(f"{b}/{p}")
            continue
        key = f"{b}/{p}"
        fname = f"{b}_{p:04d}.png"
        shutil.copyfile(src, out / fname)
        doc = simplify_doc(doc)
        doc.pop("expected_cols", None)
        drafts[key] = doc
        pages.append({"key": key, "book": b, "page": p, "file": fname, "stratum": pk.get("stratum"),
                      "hint": pk.get("hint", ""), "split": pk.get("split")})
    (out / "drafts.json").write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
    (out / "pack.json").write_text(json.dumps(
        {"id": pack_id, "book": book, "source_rev": source_rev, "pages": pages}, ensure_ascii=False),
        encoding="utf-8")
    return {"pages": len(pages), "missing": miss}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", required=True)
    ap.add_argument("--raw-root", required=True)
    ap.add_argument("--pick", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack-id", required=True)
    ap.add_argument("--source-rev", type=int)
    a = ap.parse_args(argv)
    r = build(Path(a.products), Path(a.raw_root), json.loads(Path(a.pick).read_text(encoding="utf-8")),
              Path(a.out), a.pack_id, a.source_rev)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
