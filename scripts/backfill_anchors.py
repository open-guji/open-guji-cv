# -*- coding: utf-8 -*-
"""老裁决补锚：给没有锚的逐格裁决事件写一份持久补锚档（设计见 `feedback/anchor_backfill.py` 模块头）。

    PYTHONIOENCODING=utf-8 .venv/bin/python scripts/backfill_anchors.py vol02 -w <工作区> \\
        [--align-products <另一份产物根>] [--write] [--report 报告.json]

- 不带 `--write` 只算不写，打印「锚上／锚不上」各多少、各是什么原因。
- `--write` 覆盖写 `feedback/anchors/<book>.jsonl`（锚不上的也写一行，`anchor` 为 null、写原因），
  并把用到的当时图块按内容存进 `feedback/anchor_patches/<book>/`。
- 现行切分取 `GUJI_PRODUCTS_DIR`（缺省工作区 `products/`）里的 Step3；整理本对照取 Step5-d `align_ref`，
  现行产物里没有 Step5-d 时用 `--align-products` 指另一份产物根，**只收几何与现行切分一致（≤3px）的格**。
- 只动锚，不动人裁内容；事件日志不改。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--align-products", default=None, help="取 align_ref 的另一份产物根（现行产物没有 Step5-d 时）")
    ap.add_argument("--write", action="store_true", help="写补锚档（缺省只算不写）")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())

    import cv2

    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.workspace import glyph_store_path
    from open_guji_cv.feedback.anchor import parse_cell_key, store_patch
    from open_guji_cv.feedback.anchor_backfill import anchors_path, build_page
    from open_guji_cv.feedback.bindings import _cell_index, _verdict_events
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import CELLS_KIND, cells_step

    book = a.book
    store = ProductStore()
    astore = ProductStore(Path(a.align_products)) if a.align_products else store
    step = cells_step(book)
    bk = load_book(book)
    gstore = glyph_store_path()
    labels = {}
    for f in (gstore / "instances").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if d["instance_id"].startswith(f"v2:{book}:"):
                    labels[d["instance_id"][3:]] = d.get("label")

    def patch_for(key: str):
        p = gstore / "patches" / f"v2_{key.replace(':', '_')}.png"
        if not p.exists() or key not in labels:
            return None
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        return None if img is None else (p, img, labels[key])

    def align_for(page: int, idx: dict) -> dict:
        d = astore.read_raw(book, "align_ref", page_key(page))
        if not d:
            return {}
        other = idx
        if astore is not store:
            oc = astore.read(book, step, page_key(page), CELLS_KIND)
            other = _cell_index(oc) if oc is not None else {}
        out = {}
        for c in d["align_ref"]["chars"]:
            pk = parse_cell_key(c["id"])
            if pk is None or not c.get("align_char"):
                continue
            k = (pk[2], pk[3], pk[4])
            if k in idx and k in other and all(abs(x - y) <= 3 for x, y in zip(idx[k][0], other[k][0])):
                out[k] = c["align_char"]
        return out

    todo = {pg: [e for e in evs if not (e.target.anchor and e.target.anchor.get("bbox"))]
            for pg, evs in _verdict_events(book, EventLog()).items()}
    rows = []
    for page in sorted(todo):
        evs = todo[page]
        if not evs:
            continue
        cells = store.read(book, step, page_key(page), CELLS_KIND)
        idx = _cell_index(cells) if cells is not None else {}
        raw_path = bk.raw_path(page) if hasattr(bk, "raw_path") else None
        loader = (lambda rp=raw_path: cv2.imread(str(rp), cv2.IMREAD_GRAYSCALE))
        rows += build_page(book, page, evs, cells, store.sha(book, step, page_key(page)), loader,
                           patch_for, align_for(page, idx),
                           store_patch_fn=(lambda p: store_patch(book, p)) if a.write else None)

    by = Counter((r["evidence"].get("method") or "none") for r in rows)
    shaped = [r for r in rows if r["shape"]]
    print(f"{book}：无锚老事件 {len(rows)} 条（带字 {len(shaped)}）")
    print("  补锚方法：", dict(by))
    print("  带字的：锚上", sum(1 for r in shaped if r["anchor"]), "／锚不上", sum(1 for r in shaped if not r["anchor"]))
    print("  墨框落点：", dict(Counter(("同编号" if r["evidence"].get("at") and f"{book}:{parse_cell_key(r['key'])[1]}:{r['evidence']['at']}" == r["key"]
                                      else "跨格" if r["evidence"].get("at") is None else "别的编号")
                                     for r in rows if r["evidence"].get("method") == "ink")))
    print("  上下文核对：", dict(Counter(r["evidence"].get("ctx") for r in rows if r["anchor"])))
    why = defaultdict(list)
    for r in rows:
        if not r["anchor"]:
            why[r["evidence"].get("reason", "").split("（")[0].split("，")[0][:24]].append(r["key"])
    for k, v in sorted(why.items(), key=lambda kv: -len(kv[1])):
        print(f"  锚不上 {len(v):4d}  {k}  例：{'、'.join(sorted(set(v))[:4])}")
    if a.write:
        f = anchors_path(book)
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("已写", f)
    if a.report:
        Path(a.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
