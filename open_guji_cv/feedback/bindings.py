# -*- coding: utf-8 -*-
"""人裁 → 现在哪一格：绑定表。切分一变按页自动重算，下游一律经它读人裁。

设计见 overview `进度/总览/15-人裁锚定与重切后重绑定.md`；锚的格式见 `anchor.py`。

## 状态

| 状态 | 条件 | 下游 |
|---|---|---|
| `valid` | 锚框与**同编号**的现格是同一块：框几乎没动（IoU ≥ `IOU_SAME`），或重合/包含且图块像 | 照常采信 |
| `rebound` | 同上，但落在**另一个编号**上——列内多切/少切一格后整列顺移的那种 | 改绑到新编号采信 |
| `review` | 切开（锚框里落着两个以上的现格）、合并、只部分重合，或重合但图块不像 | **不采信**，回待审 |

「框几乎没动就不看图块」：原图不变，同一块像素就是同一个字；而字块图会因 Step4 去噪、收紧、
掩膜改动而变——bxgb 实测 6 条框完全没动（IoU=1.0）、图块相似度却只有 0.61~0.87，看图块会误判成待审。
「包含」：夹注判法改了之后格只剩右半（bxgb `3:4:5`「覿」，IoU 0.50），新格整个落在锚框里、且锚框里只有它一格 → 看图块。
| `void` | 锚框处已经没有格 | 不采信 |
| `unanchored` | 老裁决、既补不出框也没有当时的图：裁于现行切分之后 → 视同 valid；之前 → 不采信 | 同左 |

没有框、但字形库里有当时的图（老裁决常见）：同编号现格的图像 → `valid`，不像 → `review`。

## 老裁决补锚（事件里 `target.anchor` 为空）

几何：按裁决时间找**当时那一版** Step3 产物——现行版（manifest 时间之后的裁决）、`_prev/` 上一版、
`<step>.bak-YYYYMMDD/` 手工备份——取那一版里这个编号的 `quad_page`。原图不变，所以当时的框与现在的框可比。
图块：字形库里入库的人裁存了当时的图块（`instances.patch_png`），拿来与现格比。

## 缓存与及时性

每页一份 `feedback/bindings/<book>/pNNNN.json`，记算它时的 Step3 产物 sha 与本页裁决事件的签名；
二者任一变了（重切了 / 有新裁决）就在下一次读的时候重算。所以**不用记得去跑**，谁读谁触发。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .anchor import parse_cell_key, patch_key, patch_path, quad_bbox

IOU_SAME = 0.85       # 框几乎没动：原图上同一块像素，必是同一个字，不再看图块（图块会因 Step4 去噪/收紧而变）
IOU_OK = 0.6          # 重合到这个程度、且图块也像，才算「还是那一格」
IOU_GONE = 0.15       # 低于这个算「那一格没了」
SIM_OK = 0.90         # 图块相似度（elastic cov）；vol02 漂移检查：未动的 1,122 条 ≥0.9，漂移的 30 条 <0.9
USE_STATUSES = ("valid", "rebound")
_MEMO: dict = {}
_VERSION = 3          # 判定规则/行格式改了就加 1，缓存自动作废


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _bindings_dir(book: str) -> Path:
    from ..core.workspace import feedback_root
    return feedback_root() / "bindings" / book


def _cells_versions(book: str, page: int, store) -> list[tuple[str, float, float, object]]:
    """[(标签, 起, 止, PageCells)]，按「止」升序。现行版 起=manifest 时间、止=∞；上一版、备份版 起=-∞。"""
    from ..core.spec import page_key
    from ..products.kinds.cells import PageCells
    from ..report.slots import CELLS_KIND, cells_step
    step, key = cells_step(book), page_key(page)
    out = []
    cur = store.read(book, step, key, CELLS_KIND)
    ent = store.manifest(book, step).get(key)
    cur_ts = float(ent.ts) if ent is not None else 0.0
    prev = store.read_prev(book, step, key, CELLS_KIND)
    if prev is not None:
        out.append(("prev", float("-inf"), cur_ts, prev))
    for d in sorted(store.step_dir(book, step).parent.glob(f"{step}.bak-*")):
        f = d / f"{key}.json"
        if not f.exists():
            continue
        try:
            day = datetime.strptime(d.name.rsplit("-", 1)[-1], "%Y%m%d")
            raw = json.loads(f.read_text(encoding="utf-8"))
            out.append((f"bak:{d.name.rsplit('-', 1)[-1]}", float("-inf"),
                        day.timestamp() + 86400, PageCells.model_validate(raw[CELLS_KIND])))
        except Exception:
            continue
    out.sort(key=lambda t: t[2])
    if cur is not None:
        out.append(("current", cur_ts, float("inf"), cur))
    return out


def _cell_index(cells) -> dict[str, tuple[list[float], str]]:
    book_pages = {}
    for cc in cells.columns:
        for c in cc.cells:
            if c.quad_page:
                book_pages[(cc.col, c.slot, c.sub or "")] = (quad_bbox(c.quad_page), c.kind)
    return book_pages


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _inside(inner, outer) -> float:
    """inner 框有多大比例落在 outer 里。"""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return ix * iy / area if area > 0 else 0.0


def _legacy_anchor(ev, book, page, col, slot, sub, versions, glyph_db) -> dict | None:
    t = _ts(ev.ts)
    pick = None
    for label, start, end, cells in versions:
        if end > t and start <= t:
            pick = (label, cells)
            break
    a: dict = {"source": "backfill"}
    if pick is not None:
        hit = _cell_index(pick[1]).get((col, slot, sub))
        if hit:
            a["bbox"] = hit[0]
            a["source"] = f"backfill:{pick[0]}"
    if glyph_db is not None:
        row = glyph_db.execute(
            "SELECT patch_png FROM instances WHERE instance_id IN (?, ?) AND label_status='human'",
            (f"v2:{ev.target.key}", ev.target.key)).fetchone()
        if row:
            a["content_png"] = row[0]            # 只在内存里用，不落盘
    return a if ("bbox" in a or "content_png" in a) else None


def _similar(anchor: dict, book: str, cur_patch: Path | None) -> float | None:
    """锚里的图块 vs 现格字块：elastic cov。任一侧没图 → None。"""
    if cur_patch is None:
        return None
    import cv2
    import numpy as np
    from ..clustering.normalize import normalize_patch
    from ..clustering.verify import verify_pair_elastic
    from ..utils.image_io import imread
    if anchor.get("content_png"):
        old = cv2.imdecode(np.frombuffer(anchor["content_png"], np.uint8), cv2.IMREAD_GRAYSCALE)
    elif anchor.get("content_sha") and patch_path(book, anchor["content_sha"]).exists():
        old = imread(str(patch_path(book, anchor["content_sha"])), cv2.IMREAD_GRAYSCALE)
    else:
        return None
    cur = imread(str(cur_patch), cv2.IMREAD_GRAYSCALE)
    if old is None or cur is None:
        return None
    return float(verify_pair_elastic(normalize_patch(cur), normalize_patch(old)).f1)


def _verdict_events(book: str, log) -> dict[int, list]:
    """本书逐格裁决事件（confirm 类），按页分组、按时间排序。"""
    out: dict[int, list] = {}
    for e in sorted(log.iter_all(), key=lambda e: (e.ts, e.batch, e.seq)):
        if e.kind != "confirm" or e.target.unit != "cell":
            continue
        pk = parse_cell_key(e.target.key)
        if pk is None or pk[0] != book:
            continue
        out.setdefault(pk[1], []).append(e)
    return out


def compute_page(book: str, page: int, events: list, store=None, cache=None, glyph_db=None) -> list[dict]:
    """一页裁决的绑定（不读不写缓存）。"""
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    store = store or ProductStore()
    cache = cache or ImageCache()
    versions = _cells_versions(book, page, store)
    current = versions[-1] if versions and versions[-1][0] == "current" else None
    cur_idx = _cell_index(current[3]) if current else {}
    cur_start = current[1] if current else 0.0
    rows = []
    for ev in events:
        _, _, col, slot, sub = parse_cell_key(ev.target.key)
        anchor = ev.target.anchor if (ev.target.anchor and ev.target.anchor.get("bbox")) else None
        if anchor is None:
            anchor = _legacy_anchor(ev, book, page, col, slot, sub, versions, glyph_db)
        row = {"event": ev.id, "key": ev.target.key, "ts": ev.ts, "bound": None,
               "shape": (ev.payload or {}).get("shape") or None,
               "status": "void", "iou": 0.0, "sim": None,
               "anchor": None if anchor is None else anchor.get("source", "live")}
        if anchor is None or not anchor.get("bbox"):
            # 补不出几何：裁于现行切分之后 → 同编号照用；之前 → 回待审（宁可重看不可错用）
            same = (col, slot, sub) in cur_idx
            sim = (_similar(anchor, book, cache.get(book, "char_patch", patch_key(page, col, slot, sub)))
                   if anchor is not None and same else None)
            row["sim"] = None if sim is None else round(sim, 4)
            if sim is not None:
                # 没有框、但有当时的图：同编号现格的图还像 → 仍有效；不像 → 回待审
                row["status"] = "valid" if sim >= SIM_OK else "review"
                row["bound"] = ev.target.key
            else:
                row["status"] = "unanchored"
                row["bound"] = ev.target.key if (same and _ts(ev.ts) >= cur_start) else None
            rows.append(row)
            continue
        best, best_iou, inside = None, 0.0, 0
        ab = anchor["bbox"]
        for (c, s, sb), (bb, kind) in cur_idx.items():
            v = _iou(ab, bb)
            if v > best_iou:
                best, best_iou = (c, s, sb), v
            if _inside(bb, ab) >= 0.5:            # 这个现格大半落在锚框里
                inside += 1
        row["iou"] = round(best_iou, 3)
        if best is None or best_iou < IOU_GONE:
            rows.append(row)                     # void
            continue
        bkey = f"{book}:{page}:{best[0]}:{best[1]}{best[2]}"
        row["bound"] = bkey
        same = "valid" if bkey == ev.target.key else "rebound"
        if best_iou >= IOU_SAME:
            row["status"] = same
            rows.append(row)
            continue
        sim = _similar(anchor, book, cache.get(book, "char_patch", patch_key(page, *best)))
        row["sim"] = None if sim is None else round(sim, 4)
        contained = _inside(cur_idx[best][0], ab) >= 0.9 and inside == 1   # 格缩了（夹注只剩半边等）
        if (best_iou >= IOU_OK or contained) and inside <= 1 and (sim is None or sim >= SIM_OK):
            row["status"] = same
        else:
            row["status"] = "review"
        rows.append(row)
    return rows


def _sig(events) -> str:
    return f"{len(events)}:{events[-1].id if events else ''}"


def page_bindings(book: str, page: int, events: list, store=None, cache=None, glyph_db=None,
                  refresh: bool = False) -> list[dict]:
    """读缓存；Step3 产物或本页裁决变了就重算并写回。"""
    from ..core.spec import page_key
    from ..products.store import ProductStore
    from ..report.slots import cells_step
    store = store or ProductStore()
    cells_sha = store.sha(book, cells_step(book), page_key(page))
    f = _bindings_dir(book) / f"p{page:04d}.json"
    if not refresh and f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("v") == _VERSION and d.get("cells_sha") == cells_sha and d.get("sig") == _sig(events):
                return d["rows"]
        except Exception:
            pass
    rows = compute_page(book, page, events, store=store, cache=cache, glyph_db=glyph_db)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": _VERSION, "cells_sha": cells_sha, "sig": _sig(events),
                             "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             "rows": rows}, ensure_ascii=False), encoding="utf-8")
    return rows


def book_bindings(book: str, log=None, store=None, refresh: bool = False,
                  pages: list[int] | None = None) -> dict[str, dict]:
    """全书（或指定页）裁决事件 → 绑定行，`{event_id: row}`。"""
    import sqlite3

    from ..core.workspace import glyph_db_path
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from .events import EventLog
    store = store or ProductStore()
    by_page = _verdict_events(book, log or EventLog())
    # 同一次跑批里 Step7 每页都要读一遍全书绑定：事件与 Step3 产物都没变时直接用上一份（2 分钟内）
    from ..core.spec import page_key
    from ..report.slots import cells_step
    step = cells_step(book)
    sig = (book, str(store.root),
           tuple((pg, _sig(evs), store.sha(book, step, page_key(pg))) for pg, evs in sorted(by_page.items())),
           tuple(pages) if pages is not None else None)
    hit = _MEMO.get(sig)
    if hit and not refresh and time.time() - hit[0] < 120:
        return hit[1]
    cache = ImageCache()
    try:
        gdb = sqlite3.connect(str(glyph_db_path()))
    except Exception:
        gdb = None
    out: dict[str, dict] = {}
    for page, evs in by_page.items():
        if pages is not None and page not in pages:
            continue
        for r in page_bindings(book, page, evs, store=store, cache=cache, glyph_db=gdb, refresh=refresh):
            out[r["event"]] = r
    _MEMO.clear()
    _MEMO[sig] = (time.time(), out)
    return out


def usable(row: dict | None, event_ts: str | None = None) -> str | None:
    """绑定行 → 该裁决现在应落到的编号；不该采信 → None。"""
    if row is None:
        return None
    if row["status"] in USE_STATUSES:
        return row["bound"]
    if row["status"] == "unanchored":
        return row["bound"]          # 只有「裁于现行切分之后且同编号还在」才非空
    return None


def rebind_library_shapes(book: str, shapes: dict[str, str], log=None) -> dict[str, str]:
    """字形库人裁（`seed_admit._human_shapes`，按入库时的编号）→ 现在该落的编号。

    以该编号**最后一条**裁决事件的绑定状态为准：仍有效照旧、顺移了改绑、其余丢掉。
    最后一条裁决的字与库里不同（人后来改判了，库因「同一实例只准入一次」没跟上）→ 库里这份丢掉，
    由事件那条路给新字（vol02 `151:9:20` 库里「一」、09-25 改判「二」）。
    库里有而事件日志里没有的（很老的数据）原样保留——没有依据就不动，与 09-25 之前一致。
    """
    try:
        b = book_bindings(book, log)
    except Exception:
        return shapes
    latest: dict[str, dict] = {}
    for r in sorted(b.values(), key=lambda r: r["ts"]):
        latest[r["key"]] = r
    out: dict[str, str] = {}
    for k, ch in shapes.items():
        r = latest.get(k) if k.startswith(book + ":") else None
        if r is None:
            out[k] = ch
            continue
        if r.get("shape") and r["shape"] != ch:
            continue       # 库里是旧裁决，之后人改判了：让事件那条路（human_chars）给新字，库里这份作废
        nk = usable(r)
        if nk:
            out[nk] = ch
    return out
