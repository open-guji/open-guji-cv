#!/usr/bin/env python3
"""overview#279：vol02 整册重算后旧人裁的重绑定核账（不改任何事件文件、不写 ws）。

与 vol03/#266 的差别：vol02 原图没换过（无列号对照、无页位移），且 vol02 的逐格裁决事件
`target.anchor` 全是 null（没有 product_key），所以「seed_admit 指纹与快照一致」这条准入闸
对它们**无从成立**——不补新锚（anchors_vol02_all.jsonl 只含指纹确认的行，实际为空）。
ws 里已有 `feedback/anchors/vol02.jsonl`（H #H-vol02-anchor 用字块图像素反查原图补的，坐标在原图
上，不依赖 Step3），照样有效。这里做的是：用**现行** bindings.compute_page + 这份现有补锚，
对新产物算一遍，列出 valid / rebound / review / void，review/void 的进 needs_review.md。

用法：GUJI_PRODUCTS_DIR=<新产物> python rebind_vol02.py <旧快照 products 根> <workspace> <输出目录>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from open_guji_cv.feedback.anchor import ANCHOR_VERSION, SPACE, quad_bbox
from open_guji_cv.core.spec import page_key
from open_guji_cv.products import kinds as _k  # noqa: F401
from open_guji_cv.products.store import ProductStore

BOOK = "vol02"
KEY_RE = re.compile(r"^vol02:(\d+):(\d+):(\d+)([ab]?)$")


def main(snap_root: str, ws: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    old, new = ProductStore(Path(snap_root)), ProductStore()
    existing = {}
    for line in (Path(ws) / "feedback/anchors/vol02.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            existing[d["event"]] = d
    events, pages = [], set()
    for f in sorted((Path(ws) / "feedback/events").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            t = d.get("target") or {}
            m = KEY_RE.match(t.get("key", ""))
            if m and t.get("unit") == "cell" and d["kind"] == "confirm":
                d["_file"] = f.name
                events.append(d)
                pages.add(int(m.group(1)))
    # 新补锚：只补「事件带 product_key 且指纹 == 旧快照」且现有补锚档没有非空锚的
    new_anchors, fp_checked = [], 0
    for d in events:
        t = d["target"]
        pk = (t.get("anchor") or {}).get("product_key") or {}
        if not pk.get("step"):
            continue
        fp_checked += 1
        ent = old.manifest(BOOK, pk["step"]).get(pk.get("key", ""))
        if not (ent and ent.fingerprint == pk.get("fingerprint")):
            continue
        if (existing.get(d["id"]) or {}).get("anchor"):
            continue
        pg, col, slot, sub = KEY_RE.match(t["key"]).groups()
        cells = old.read(BOOK, "row_segment", page_key(int(pg)), "cells")
        quad = None
        for cc in cells.columns:
            if cc.col == int(col):
                for c in cc.cells:
                    if c.slot == int(slot) and (c.sub or "") == sub and c.quad_page:
                        quad = c.quad_page
        if quad:
            new_anchors.append({"event": d["id"], "key": t["key"], "anchor": {
                "v": ANCHOR_VERSION, "space": SPACE, "quad": quad, "bbox": quad_bbox(quad),
                "source": "backfill:s279_snapshot"}, "evidence": {"from": "cloud-20260927-cd04496 row_segment"}})
    bf = {e: r["anchor"] for e, r in existing.items() if r.get("anchor")}
    bf.update({a["event"]: a["anchor"] for a in new_anchors})
    from open_guji_cv.feedback import bindings
    from open_guji_cv.feedback.events import EventLog
    log = EventLog()
    vev = bindings._verdict_events(BOOK, log)
    rev = bindings._return_trigger_events(BOOK, log)
    res = {}
    for pg in sorted(pages):
        for r in bindings.compute_page(BOOK, pg, vev.get(pg, []), store=new, backfill=bf,
                                       return_events=rev.get(pg)):
            res[r["event"]] = r
    table = []
    for d in events:
        r = res.get(d["id"], {})
        e = existing.get(d["id"]) or {}
        table.append({"event": d["id"], "file": d["_file"], "key": d["target"]["key"], "ts": d["ts"],
                      "v": (d.get("payload") or {}).get("v"), "reading": (d.get("payload") or {}).get("reading"),
                      "has_existing_anchor": bool(e.get("anchor")),
                      "bind_status": r.get("status"), "bound": r.get("bound"), "iou": r.get("iou")})
    (out / "anchors_vol02_all.jsonl").write_text(
        "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in new_anchors), encoding="utf-8")
    (out / "rebind_table_vol02.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in table), encoding="utf-8")
    print(len(events), "cell confirms;", fp_checked, "with product_key;", len(new_anchors), "new anchors")
    print(Counter((r["has_existing_anchor"], r["bind_status"]) for r in table))


if __name__ == "__main__":
    main(*sys.argv[1:4])
