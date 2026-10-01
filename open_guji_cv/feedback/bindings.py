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

**补锚档**（`feedback/anchors/<book>.jsonl`，`anchor_backfill.py`，2026-09-28）：没有 `target.anchor` 的老事件先查这里。
锚里是 `ink_bbox`（当时字块图在原图上找回的墨框）的，按「墨框 ≥80% 落在某一现格、第二格 <20%」绑
（`anchor_backfill.bind_ink`）：落在同编号 → `valid`，别的编号 → `rebound`，跨两格 → `review`，落空 → `void`。

**图像指纹优先**（2026-10-01，D2/#323）：事件锚里带 `evidence.fp`（`anchor.evidence_for`，口径 =
`gold/drift.fingerprint`）的，先拿它与候选现格的字块图比：相同/近似（差 ≤ `drift.FP_TOL`）才认
（`valid`/`rebound` 照几何定），不像一律 `review`——**包括框几乎没动（IoU ≥ `IOU_SAME`）的**：
X2 实测切分重算后同一块像素上的格已经改成完整字，裁决却还挂着。行里多一列 `fp_diff`。现格没有字块图
（缓存没了）→ 退回下面的老规则。没有指纹的旧事件完全照老规则。

没有框、但字形库里有当时的图（老裁决常见）：同编号现格的图像 → `valid`，不像 → `review`。

## 老裁决补锚（事件里 `target.anchor` 为空、补锚档里也没有）

几何：按裁决时间找**当时那一版** Step3 产物——现行版（manifest 时间之后的裁决）、`_prev/` 上一版、
`<step>.bak-YYYYMMDD/` 手工备份——取那一版里这个编号的 `quad_page`。原图不变，所以当时的框与现在的框可比。
`_prev/` 的起点取 manifest 历史里**头一次写出这份内容**的时间；查不到就不用它（2026-09-28 修：
原来起点写死 −∞，vol02 09-27 快照导入后 `_prev` 是 09-27 的上一版，4441 条 09-06 起的老裁决
全被当成「按 `_prev` 裁的」、与现行版一比全是 valid——假有效）。
图块：字形库里入库的人裁存了当时的图块（`instances.patch_png`），拿来与现格比。

## 缓存与及时性

每页一份 `feedback/bindings/<book>/pNNNN.json`，记算它时的 Step3 产物 sha 与本页裁决事件的签名；
二者任一变了（重切了 / 有新裁决）就在下一次读的时候重算。所以**不用记得去跑**，谁读谁触发。

## `status` 与 `return_status`：两列，答的是两件不同的事（2026-09-27）

总览/13（打回台账）并入本篇（总览/15）之后，绑定行上会同时出现两组状态字段，
**别混进同一列**——对照见 overview `进度/总览/17-13并入15-字段对照.md`：

| 字段 | 答的问题 | 取值 | 谁定 |
|---|---|---|---|
| `status`（上面那张表） | 这条裁决现在还对不对得上格（认不认锚） | valid/rebound/review/void/unanchored | 重切前后的几何/图块比对，见本文件 |
| `return_to`／`return_reason`／`return_status` | 这一格的上游处理有没有问题、该退给谁、退回工单办完了没 | to_step 字符串／reason 枚举／open-fixed-wontfix | `feedback/returns.py`，从 `confirm(seg_defect)`／`cutline`／`n_body_slots` 等事件现算 |

一条裁决完全可能同时是 `status=valid`（这一格锚定还对得上）**且** `return_status=open`
（但人另外标过这一格切分有问题，该退回 Step3 重切）——两件事互不遮挡。三个 `return_*`
字段都可空：空 = 这一格没有被打回过。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..gold.drift import FP_TOL
from .anchor import parse_cell_key, patch_key, patch_path, quad_bbox

IOU_SAME = 0.85       # 框几乎没动：原图上同一块像素，必是同一个字，不再看图块（图块会因 Step4 去噪/收紧而变）
IOU_OK = 0.6          # 重合到这个程度、且图块也像，才算「还是那一格」
IOU_GONE = 0.15       # 低于这个算「那一格没了」
SIM_OK = 0.90         # 图块相似度（elastic cov）；vol02 漂移检查：未动的 1,122 条 ≥0.9，漂移的 30 条 <0.9
USE_STATUSES = ("valid", "rebound")
_MEMO: dict = {}
_VERSION = 6          # 判定规则/行格式改了就加 1，缓存自动作废（4：加 return_to/reason/status 三字段；5：补锚档、_prev 起点；6：图像指纹优先、行加 fp_diff）


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
        born = _first_written(store.manifest(book, step).path, key, store.prev_sha(book, step, key))
        if born is not None and born < cur_ts:
            out.append(("prev", born, cur_ts, prev))
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


def _first_written(manifest_path: Path, key: str, sha: str | None) -> float | None:
    """manifest 历史（追加写）里这一页头一次写出内容 `sha` 的时间；查不到 → None。

    `_prev/` 只留一代、自己不记时间，要从 manifest 反查它是什么时候生成的。
    manifest 被 `compact()` 过、或快照只带了最后一条，就查不到——那就不知道这份 `_prev`
    覆盖哪段时间，宁可不用。"""
    if not sha or not manifest_path.exists():
        return None
    best = None
    try:
        with open(manifest_path, encoding="utf-8") as f:
            for line in f:
                if f'"{key}"' not in line:
                    continue
                d = json.loads(line)
                if d.get("key") == key and d.get("sha256") == sha and d.get("ts") is not None:
                    t = float(d["ts"])
                    best = t if best is None else min(best, t)
    except (OSError, ValueError):
        return None
    return best


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


def _fp_diff(evidence: dict | None, cur_patch: Path | None) -> float | None:
    """锚里凭证的指纹 vs 现格字块图 → 平均绝对差；任一侧没有 → None（调用方退回老规则）。"""
    if not evidence or not evidence.get("fp") or cur_patch is None:
        return None
    if evidence.get("fp_of", "char_patch") != "char_patch":
        return None
    try:
        import cv2
        from ..gold.drift import FP_SIZE, fp_diff
        from ..utils.image_io import imread
        img = imread(str(cur_patch), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return fp_diff(evidence["fp"], img, tuple(evidence.get("fp_size") or FP_SIZE))
    except Exception:
        return None


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


def _return_trigger_events(book: str, log) -> dict[int, list]:
    """本书 `cutline`／`n_body_slots`／`return_resolve` 事件，按页分组、按时间排序——
    `_verdict_events` 只收 `confirm`+`unit=cell`，收不到这几种列级/结案事件（见
    `feedback/returns.py`、`compute_page` 的 `return_events` 参数）。"""
    out: dict[int, list] = {}
    for e in sorted(log.iter_all(), key=lambda e: (e.ts, e.batch, e.seq)):
        if e.kind not in ("cutline", "n_body_slots", "return_resolve"):
            continue
        if e.target.book != book or e.target.page is None:
            continue
        out.setdefault(e.target.page, []).append(e)
    return out


def compute_page(book: str, page: int, events: list, store=None, cache=None, glyph_db=None,
                 return_events: list | None = None, backfill: dict | None = None) -> list[dict]:
    """一页裁决的绑定（不读不写缓存）。

    `return_events`：这一页的 `cutline`／`n_body_slots`／`return_resolve` 事件（列级/结案，
    `_verdict_events` 收不到——它只收 `confirm`+`unit=cell`）。给了就顺带把打回字段
    （`return_to`／`return_reason`／`return_status`，见 `feedback/returns.py`）折进已有的行——
    **只折进已经因为 confirm 事件存在的行**，不为「只有列级触发、没有单独定字事件」的格
    另造新行：那类格会让 `book_bindings()` 的按事件 id 建表、`rebind_library_shapes()`
    的按 key 取最新两处逻辑多一种它们没设计过的行形状，宁可这轮先不接，留到下一轮
    专门给它们设计不冲突的落点（见 overview 总览/17 对照页 §三）。
    """
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from .anchor_backfill import bind_ink, ink_hits, load_backfill
    store = store or ProductStore()
    cache = cache or ImageCache()
    if backfill is None:
        backfill = load_backfill(book)
    versions = _cells_versions(book, page, store)
    current = versions[-1] if versions and versions[-1][0] == "current" else None
    cur_idx = _cell_index(current[3]) if current else {}
    cur_start = current[1] if current else 0.0
    rows = []
    for ev in events:
        _, _, col, slot, sub = parse_cell_key(ev.target.key)
        anchor = ev.target.anchor if (ev.target.anchor and ev.target.anchor.get("bbox")) else None
        evid = (ev.target.anchor or {}).get("evidence")
        if anchor is None:
            anchor = backfill.get(ev.id)
        if anchor is None:
            anchor = _legacy_anchor(ev, book, page, col, slot, sub, versions, glyph_db)
        row = {"event": ev.id, "key": ev.target.key, "ts": ev.ts, "bound": None,
               "shape": (ev.payload or {}).get("shape") or None,
               "status": "void", "iou": 0.0, "sim": None,
               "anchor": None if anchor is None else anchor.get("source", "live")}
        if anchor is not None and anchor.get("ink_bbox"):
            # 补锚档的墨框：当时那块墨落在现在哪一格（anchor_backfill.bind_ink）
            cell, ins, _ = bind_ink(anchor["ink_bbox"], cur_idx)
            row["iou"] = round(ins, 3)
            if cell is not None:
                row["bound"] = f"{book}:{page}:{cell[0]}:{cell[1]}{cell[2]}"
                row["status"] = "valid" if row["bound"] == ev.target.key else "rebound"
            elif ink_hits(anchor["ink_bbox"], cur_idx) and ins >= IOU_GONE:
                row["status"] = "review"          # 墨跨两格（切开/合并）
            rows.append(row)                      # 其余 void：那块墨处已经没有格
            continue
        if anchor is None or not anchor.get("bbox"):
            # 补不出几何：裁于现行切分之后 → 同编号照用；之前 → 回待审（宁可重看不可错用）
            same = (col, slot, sub) in cur_idx
            d0 = _fp_diff(evid, cache.get(book, "char_patch", patch_key(page, col, slot, sub))) if same else None
            if d0 is not None:
                row["fp_diff"] = round(d0, 1)
                row["bound"] = ev.target.key
                row["status"] = "valid" if d0 <= FP_TOL else "review"
                rows.append(row)
                continue
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
        d1 = _fp_diff(evid, cache.get(book, "char_patch", patch_key(page, *best)))
        if d1 is not None:
            # 有当时的图指纹：相同/近似才认，其余回待审（几何只负责找候选格）
            row["fp_diff"] = round(d1, 1)
            row["status"] = same if (d1 <= FP_TOL and inside <= 1) else "review"
            rows.append(row)
            continue
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

    # ── 打回：折进已有行（2026-09-27，总览/13 并入总览/15）───────────────────
    from .returns import affected_slots, classify_return, resolve_status
    by_key: dict[str, list] = {}          # 格键 → 这一格全部「打回相关」事件（触发 + 结案）
    for ev in events:
        if classify_return(ev) is not None or ev.kind == "return_resolve":
            by_key.setdefault(ev.target.key, []).append(ev)
    for ev in (return_events or []):
        if ev.kind == "return_resolve":
            by_key.setdefault(ev.target.key, []).append(ev)
            continue
        if classify_return(ev) is None:
            continue
        for (c, s, sub) in affected_slots(ev, cur_idx):
            by_key.setdefault(f"{book}:{page}:{c}:{s}{sub}", []).append(ev)
    if by_key:
        rows_by_key: dict[str, dict] = {}
        for r in rows:                     # 同一 key 可能有多条历史行，后到覆盖取最新
            rows_by_key[r["key"]] = r
        for key, hist in by_key.items():
            row = rows_by_key.get(key)
            if row is None:
                continue                   # 只有列级触发、这一格没有单独的 confirm 行：本轮不接，见函数头注释
            hist_sorted = sorted(hist, key=lambda e: (e.ts, e.batch, e.seq))
            trigger = next((e for e in reversed(hist_sorted) if classify_return(e) is not None), None)
            if trigger is None:
                continue
            to_step, reason = classify_return(trigger)
            row["return_to"] = to_step
            row["return_reason"] = reason
            row["return_status"] = resolve_status(hist_sorted)
    return rows


def _sig(events, return_events: list | None = None, backfill: dict | None = None) -> str:
    base = f"{len(events)}:{events[-1].id if events else ''}"
    if backfill:
        from .anchor_backfill import page_signature
        base = f"{base}|bf:{page_signature(backfill, [e.id for e in events])}"
    if not return_events:
        return base
    return f"{base}|{len(return_events)}:{return_events[-1].id}"


def page_bindings(book: str, page: int, events: list, store=None, cache=None, glyph_db=None,
                  refresh: bool = False, return_events: list | None = None,
                  backfill: dict | None = None) -> list[dict]:
    """读缓存；Step3 产物、本页裁决或打回相关事件变了就重算并写回。"""
    from ..core.spec import page_key
    from ..products.store import ProductStore
    from ..report.slots import cells_step
    store = store or ProductStore()
    cells_sha = store.sha(book, cells_step(book), page_key(page))
    f = _bindings_dir(book) / f"p{page:04d}.json"
    if backfill is None:
        from .anchor_backfill import load_backfill
        backfill = load_backfill(book)
    sig = _sig(events, return_events, backfill)
    if not refresh and f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("v") == _VERSION and d.get("cells_sha") == cells_sha and d.get("sig") == sig:
                return d["rows"]
        except Exception:
            pass
    rows = compute_page(book, page, events, store=store, cache=cache, glyph_db=glyph_db,
                       return_events=return_events, backfill=backfill)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": _VERSION, "cells_sha": cells_sha, "sig": sig,
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
    log = log or EventLog()
    from .anchor_backfill import load_backfill
    by_page = _verdict_events(book, log)
    by_page_returns = _return_trigger_events(book, log)
    backfill = load_backfill(book)
    # 同一次跑批里 Step7 每页都要读一遍全书绑定：事件与 Step3 产物都没变时直接用上一份（2 分钟内）
    from ..core.spec import page_key
    from ..report.slots import cells_step
    step = cells_step(book)
    all_pages = sorted(set(by_page) | set(by_page_returns))
    sig = (book, str(store.root),
           tuple((pg, _sig(by_page.get(pg, []), by_page_returns.get(pg), backfill),
                 store.sha(book, step, page_key(pg))) for pg in all_pages),
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
    for page in all_pages:
        if pages is not None and page not in pages:
            continue
        evs = by_page.get(page, [])
        for r in page_bindings(book, page, evs, store=store, cache=cache, glyph_db=gdb, refresh=refresh,
                               return_events=by_page_returns.get(page), backfill=backfill):
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
