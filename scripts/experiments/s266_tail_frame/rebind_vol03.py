#!/usr/bin/env python3
"""overview#266：vol03 p49、p105–108 上旧人裁的重绑定（不改任何事件文件）。

旧裁决的事件里 `target.anchor` 只有 product_key、没有框，`bindings.compute_page` 会先查补锚档
`feedback/anchors/<book>.jsonl`，查不到才去翻产物历史（`_prev/`、备份）——而快照导入会把产物
历史换掉，105–108 更是连原图都换了（按版心中线重切），产物历史里的旧框与新原图对不上。

所以这里给这些事件补一份**新原图坐标系下**的锚（补锚档格式，`source: backfill:s266_remap`）：
- 框取自旧快照 Step3（`snap/.../row_segment`）里这一格的 `quad_page`；
- 105–108 按重切前后裁切框的位移换算到新原图（右上原点）：
  x_left_new = x_left_old + page_x_shift，x_r = W - 1 - x_left；y_new = y_old + page_y_shift（107/108 −170）；
- 49 原图没换，框原样。

然后用**现行** `bindings.compute_page`（传入这份补锚）对新产物算一遍绑定，报 valid / rebound / review / void。
列级事件（`cutline`，打回台账用，不进绑定行）按列号对照表 `s266_col_remap_vol03.json` 换列号。

用法：
  GUJI_PRODUCTS_DIR=<新产物> python rebind_vol03.py <旧快照 products 根> <workspace> <输出目录> [s266|all]
"""
import json
import re
import sys
from pathlib import Path

from open_guji_cv.core.spec import page_key
from open_guji_cv.feedback.anchor import ANCHOR_VERSION, SPACE, quad_bbox
from open_guji_cv.products import kinds as _k  # noqa: F401  (注册产物种类)
from open_guji_cv.products.store import ProductStore

PAGES = (49, 105, 106, 107, 108)
SHIFTED = (105, 106, 107, 108)          # 原图换过的页
REMAP = json.loads((Path(__file__).resolve().parents[3] / "artifacts/s266_col_remap_vol03.json").read_text())
KEY_RE = re.compile(r"^vol03:(\d+):(\d+):(\d+)([ab]?)$")


def old_width(snap_root: Path, page: int) -> int:
    d = json.loads((snap_root / "vol03/page_survey" / f"{page_key(page)}.json").read_text())
    return int(d["page_survey"]["width"])


def new_width(store: ProductStore, page: int) -> int:
    d = json.loads(store.path("vol03", "page_survey", page_key(page)).read_text())
    return int(d["page_survey"]["width"])


def shift_quad(quad, page, w_old, w_new):
    s = int(REMAP["page_x_shift"].get(str(page), 0))
    dy = int(REMAP.get("page_y_shift", {}).get(str(page), 0))
    out = []
    for x_r, y in quad:
        x_left = (w_old - 1 - x_r) + s
        out.append([round(w_new - 1 - x_left, 2), round(y + dy, 2)])
    return out


def main(snap_root: str, ws: str, out_dir: str, scope: str = "s266") -> None:
    """scope=s266：只做 49、105–108；scope=all：全书所有没框的逐格裁决都补（其余页原图没换、框原样）。"""
    global PAGES
    if scope == "all":
        PAGES = tuple(range(1, 111))
    snap_root, out = Path(snap_root), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    old = ProductStore(snap_root)
    new = ProductStore()
    events = []
    for f in sorted((Path(ws) / "feedback/events").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            m = KEY_RE.match((d.get("target") or {}).get("key", ""))
            if m and int(m.group(1)) in PAGES:
                d["_file"] = f.name
                events.append(d)
    old_cells = {pg: old.read("vol03", "row_segment", page_key(pg), "cells") for pg in PAGES}
    if scope == "all":
        # 已有框的事件不用补
        events = [d for d in events if not ((d["target"].get("anchor") or {}).get("bbox"))]
    anchors, table = [], []
    for d in events:
        t = d["target"]
        pg, col, slot, sub = (int(x) if x.isdigit() else x for x in KEY_RE.match(t["key"]).groups())
        pk = (t.get("anchor") or {}).get("product_key") or {}
        ent = old.manifest("vol03", pk.get("step", "")).get(pk.get("key", "")) if pk.get("step") else None
        snap_match = bool(ent and ent.fingerprint == pk.get("fingerprint"))
        new_col = REMAP["map"][str(pg)].get(str(col)) if str(pg) in REMAP["map"] else col
        row = {"event": d["id"], "file": d["_file"], "kind": d["kind"], "unit": t.get("unit"),
               "key": t["key"], "ts": d["ts"], "v": (d.get("payload") or {}).get("v"),
               "shape": (d.get("payload") or {}).get("shape") or None,
               "old_col": col, "new_col": new_col, "col_null": new_col is None,
               "anchor_version_matches_snapshot": snap_match}
        quad = None
        for cc in old_cells[pg].columns:
            if cc.col == col:
                same = [c for c in cc.cells if c.slot == slot and c.quad_page]
                exact = [c for c in same if (c.sub or "") == (sub or "")]
                if exact:
                    quad = exact[0].quad_page
                elif same and not sub:
                    # 事件记的是整格（无 a/b），快照里这格已拆成雙行小注 a/b → 取两半的外接框
                    xs = [p[0] for c in same for p in c.quad_page]
                    ys = [p[1] for c in same for p in c.quad_page]
                    quad = [[max(xs), min(ys)], [min(xs), min(ys)], [min(xs), max(ys)], [max(xs), max(ys)]]
        if scope == "all" and not snap_match:
            quad = None       # 裁的不是快照这一版（seed_admit 指纹对不上）：框未必是人当时看的那格，不补，留给现行规则
        if d["kind"] == "confirm" and t.get("unit") == "cell" and quad is not None:
            if pg in SHIFTED:
                quad = shift_quad(quad, pg, old_width(snap_root, pg), new_width(new, pg))
            anchors.append({"event": d["id"], "key": t["key"],
                            "anchor": {"v": ANCHOR_VERSION, "space": SPACE, "quad": quad, "bbox": quad_bbox(quad),
                                       "source": "backfill:s266_remap"},
                            "evidence": {"from": "snap/96mid1ogzk/vol03/20260928T1708-full row_segment",
                                         "page_x_shift": REMAP["page_x_shift"].get(str(pg), 0),
                                         "page_y_shift": REMAP.get("page_y_shift", {}).get(str(pg), 0),
                                         "anchor_version_matches_snapshot": snap_match}})
        table.append(row)
    # 现行绑定规则算一遍
    from open_guji_cv.feedback import bindings
    from open_guji_cv.feedback.events import EventLog
    bf = {a["event"]: a["anchor"] for a in anchors}
    log = EventLog()
    vev = bindings._verdict_events("vol03", log)
    rev = bindings._return_trigger_events("vol03", log)
    res = {}
    for pg in PAGES:
        for r in bindings.compute_page("vol03", pg, vev.get(pg, []), store=new, backfill=bf,
                                       return_events=rev.get(pg)):
            res[r["event"]] = r
    for row in table:
        r = res.get(row["event"])
        if r:
            row.update({"bind_status": r["status"], "bound": r["bound"], "iou": r["iou"]})
    (out / f"anchors_vol03_{scope}.jsonl").write_text(
        "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in anchors), encoding="utf-8")
    (out / f"rebind_table_vol03_{scope}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in table), encoding="utf-8")
    print(len(events), "events;", len(anchors), "anchors;", sum(r["col_null"] for r in table), "on null columns")


if __name__ == "__main__":
    main(*sys.argv[1:5])
