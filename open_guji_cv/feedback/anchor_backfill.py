# -*- coding: utf-8 -*-
"""老裁决补锚档：不依赖产物历史版本，给没有锚的老事件补一份持久的锚（2026-09-28，H 道 overview#152）。

## 为什么要这一份

`bindings._legacy_anchor` 现场补锚，靠的是**裁决当时那一版 Step3**（`_prev/`、`<step>.bak-*`）。
这些历史版本不跟着快照走：vol02 09-27 云端整书重跑、以快照导入之后，产物里只剩 09-27 的两版，
4439 条 09-06～09-12 的老裁决全部补不出框（`unanchored`），`human_chars(vol02)` 绑定后只剩 2 条。

所以补锚要落成**跟事件同级的持久数据**，而不是每次从产物历史里现找：
`feedback/anchors/<book>.jsonl`，一行一条事件：`{"event", "key", "anchor", "evidence"}`。
`bindings.compute_page` 对没有 `target.anchor` 的事件先查这里，查不到才走老的现场补锚。
事件日志本身不动（只追加的历史）。

## 两条补法

| 来源 | 依据 | 锚里存什么 |
|---|---|---|
| `backfill:ink` | 字形库入库时存下的**当时字块图**（`glyph_store/patches/v2_<key>.png`），在**原图**上做模板匹配找回它的位置。原图不变，所以这一路跟切分改过几轮无关 | `ink_bbox`：当时那块墨在原图上的外接框（右上原点，与 `quad_page` 同一坐标系） |
| `backfill:ctx` | 没有当时图块的：整理本（Step5-d `align_char`）在同列 ±2 格内**只有一处**是裁决的字，且落点是同编号；或落点顺移了 d 格、而同列有旁证——墨框补上的邻格顺移同为 d，或同列 ≥3 个字位各自唯一对上、顺移全是 d（整列顺移） | `bbox`：现格的框 |

两路都要过**上下文核对**（裁的字 vs 整理本对到那一格的字）才写；对不上的不写，列进报告。
`ink_bbox` 在绑定时按「墨框大半落在哪个现格里、且只落在一个格里」判（`bindings._bind_ink`），
以后再重切也照样能找回——比「当时格框」更贴近「人看的是哪个字」。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

BACKFILL_VERSION = 1
NCC_OK = 0.60          # 模板匹配峰值门槛（vol02 标定见 overview#152 评论）
NCC_MARGIN = 0.15      # 峰值要比第二峰高出这么多，否则位置有歧义
INK_INSIDE_OK = 0.80   # 墨框落在某个现格里的比例 ≥ 这个 → 就是那一格
INK_INSIDE_2ND = 0.20  # 第二个现格也吃进这么多墨 → 跨格（切开/合并），不认
COL_CTX_MIN = 3        # 整列顺移要同列至少这么多个字位（各自整理本唯一对上）顺移一致、且无反例


def anchors_path(book: str) -> Path:
    from ..core.workspace import feedback_root
    return feedback_root() / "anchors" / f"{book}.jsonl"


def load_backfill(book: str) -> dict[str, dict]:
    """`{event_id: anchor}`；没有档 → 空。"""
    f = anchors_path(book)
    if not f.exists():
        return {}
    out: dict[str, dict] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("anchor"):
            out[d["event"]] = d["anchor"]
    return out


def page_signature(anchors: dict[str, dict], event_ids: list[str]) -> str:
    """本页事件对应的补锚内容摘要：补锚档改了，这一页的绑定缓存就要重算。"""
    h = hashlib.sha1()
    for eid in event_ids:
        a = anchors.get(eid)
        if a is not None:
            h.update(eid.encode())
            h.update(json.dumps(a, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


# ── 原图定位 ────────────────────────────────────────────────────────────────

def ink_crop(patch: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    """字块图（白底黑字）→ 墨的外接框裁图与框；全白 → None。"""
    m = patch < 128
    if not m.any():
        return None
    ys, xs = np.where(m)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    return patch[y0:y1, x0:x1], (x0, y0, x1, y1)


def locate(raw: np.ndarray, patch: np.ndarray, window: tuple[int, int, int, int] | None = None
           ) -> dict | None:
    """在原图 `raw`（左上原点、白底黑字）里找字块图 `patch` 的墨。

    返回 `{"ink_bbox": [x0,y0,x1,y1]（右上原点）, "ncc", "ncc2"}`；墨太少/窗口太小 → None。
    `window`：左上原点的搜索窗 `(x0, y0, x1, y1)`。"""
    import cv2
    c = ink_crop(patch)
    if c is None:
        return None
    t = c[0]
    if t.shape[0] < 6 or t.shape[1] < 6:
        return None
    H, W = raw.shape[:2]
    wx0, wy0, wx1, wy1 = window or (0, 0, W, H)
    wx0, wy0 = max(0, int(wx0)), max(0, int(wy0))
    wx1, wy1 = min(W, int(wx1)), min(H, int(wy1))
    region = raw[wy0:wy1, wx0:wx1]
    if region.shape[0] < t.shape[0] or region.shape[1] < t.shape[1]:
        return None
    r = cv2.matchTemplate((255 - region).astype(np.float32), (255 - t).astype(np.float32),
                          cv2.TM_CCOEFF_NORMED)
    _, mx, _, (lx, ly) = cv2.minMaxLoc(r)
    # 第二峰：挖掉主峰附近（半个模板大小）再找
    r2 = r.copy()
    hy, hx = max(1, t.shape[0] // 2), max(1, t.shape[1] // 2)
    r2[max(0, ly - hy):ly + hy + 1, max(0, lx - hx):lx + hx + 1] = -1.0
    second = float(r2.max()) if r2.size else -1.0
    x0, y0 = wx0 + lx, wy0 + ly
    x1, y1 = x0 + t.shape[1], y0 + t.shape[0]
    return {"ink_bbox": [float(W - x1), float(y0), float(W - x0), float(y1)],
            "ncc": round(float(mx), 4), "ncc2": round(second, 4)}


def ink_hits(ink_bbox, cells_index: dict) -> list[tuple[float, tuple]]:
    """墨框落在各现格里的比例，降序 `[(比例, (col, slot, sub))]`（只列 > 0 的）。"""
    from .bindings import _inside
    out = [(_inside(ink_bbox, bb), k) for k, (bb, _kind) in cells_index.items()]
    return sorted([h for h in out if h[0] > 0], key=lambda h: -h[0])


def bind_ink(ink_bbox, cells_index: dict) -> tuple[tuple | None, float, float]:
    """墨框 → 现格：`(格, 落在里面的比例, 第二格的比例)`；跨格或落空 → 格为 None。"""
    hits = ink_hits(ink_bbox, cells_index)
    if not hits:
        return None, 0.0, 0.0
    best, second = hits[0], (hits[1][0] if len(hits) > 1 else 0.0)
    if best[0] >= INK_INSIDE_OK and second < INK_INSIDE_2ND:
        return best[1], best[0], second
    return None, best[0], second


# ── 构建 ────────────────────────────────────────────────────────────────────

def same_char(a: str | None, b: str | None) -> bool:
    """同字或异体（含 己/已/巳 一族：本族字形本就不分）。"""
    if not a or not b:
        return False
    if a == b:
        return True
    from ..utils.ji_yi_si import FAMILY
    if a in FAMILY and b in FAMILY:
        return True
    try:
        from ..variants import are_variants
        return bool(are_variants(a, b))
    except Exception:
        return False


def _ctx_word(shape: str | None, align: str | None) -> str:
    if not align:
        return "none"
    if shape == align:
        return "equal"
    return "variant" if same_char(shape, align) else "differ"


def build_page(book: str, page: int, events: list, cells, cells_sha: str | None,
               raw_loader, patch_for, align: dict, store_patch_fn=None) -> list[dict]:
    """一页老事件 → 补锚行（锚不上的 `anchor` 为 None、`evidence.reason` 写原因）。

    - `cells`：现行 Step3 产物（PageCells）；`raw_loader()` → 原图（灰度，左上原点）。
    - `patch_for(key)` → `(路径, 灰度图, 入库字)` 或 None：字形库里当时那块图。
    - `align`：`{(col, slot, sub): 整理本对到这一格的字}`（Step5-d `align_char`），只收几何与现行切分一致的格。
    - `store_patch_fn(path)` → 图块 sha（存进 `feedback/anchor_patches/`）；不给就不存。
    """
    from .anchor import SPACE, parse_cell_key
    from .bindings import _cell_index
    idx = _cell_index(cells) if cells is not None else {}
    colx: dict[int, list[float]] = {}
    for (c, _s, _sb), (bb, _k) in idx.items():
        a = colx.setdefault(c, [1e9, -1e9])
        a[0], a[1] = min(a[0], bb[0]), max(a[1], bb[2])
    raw = None
    ink: dict[str, dict | None] = {}

    def locate_key(key: str) -> dict | None:
        nonlocal raw
        if key in ink:
            return ink[key]
        ink[key] = None
        p = patch_for(key)
        pk = parse_cell_key(key)
        xs = [colx[c] for c in (pk[2] - 1, pk[2], pk[2] + 1) if c in colx]
        if p is None or not xs:
            return None
        if raw is None:
            raw = raw_loader()
        W, H = raw.shape[1], raw.shape[0]
        lo, hi = min(x[0] for x in xs) - 60, max(x[1] for x in xs) + 60
        r = locate(raw, p[1], (W - hi, 0, W - lo, H))
        if r is None:
            return None
        r["located"] = r["ncc"] >= NCC_OK and r["ncc"] - r["ncc2"] >= NCC_MARGIN
        cell, ins, ins2 = bind_ink(r["ink_bbox"], idx)
        r.update(cell=cell, ins=round(ins, 3), ins2=round(ins2, 3), label=p[2], path=p[0])
        ink[key] = r
        return r

    # 先把本页有当时图块的格都定位一遍：同列顺移的旁证要用
    shift: dict[int, list[tuple[int, int]]] = {}
    for ev in events:
        k = ev.target.key
        r = locate_key(k)
        if r and r["located"] and r["cell"] is not None:
            pk = parse_cell_key(k)
            if r["cell"][0] == pk[2]:
                shift.setdefault(pk[2], []).append((pk[3], r["cell"][1] - pk[3]))

    # 上下文那一路的整列旁证：没走通墨框的带字事件里，同列 ±2 格内整理本只一处是裁的字 → 记下顺移量；
    # 同列 ≥ COL_CTX_MIN 个字位顺移一致、没有反例 → 整列顺移（切分多/少了一格，这一处以下整列错一位）
    def ctx_offset(key: str, shape: str | None) -> tuple[int | None, list]:
        _, _, col, slot, _sub = parse_cell_key(key)
        win = [(k, ch) for k, ch in align.items()
               if k[0] == col and abs(k[1] - slot) <= 2 and same_char(ch, shape)]
        return (win[0][0][1] - slot if len(win) == 1 else None), win

    col_ctx: dict[int, dict[str, int]] = {}
    for ev in events:
        k, shape = ev.target.key, (ev.payload or {}).get("shape") or None
        r = ink.get(k)
        if shape is None or (r and r["located"] and same_char(r["label"], shape)):
            continue
        off, _ = ctx_offset(k, shape)
        if off is not None:
            col_ctx.setdefault(parse_cell_key(k)[2], {})[k] = off
    col_shift: dict[int, int] = {}
    for c, offs in col_ctx.items():
        vals = set(offs.values())
        if len(offs) >= COL_CTX_MIN and len(vals) == 1:
            col_shift[c] = vals.pop()

    rows = []
    for ev in events:
        key = ev.target.key
        _, _, col, slot, sub = parse_cell_key(key)
        shape = (ev.payload or {}).get("shape") or None
        row = {"event": ev.id, "key": key, "ts": ev.ts, "shape": shape, "anchor": None, "evidence": {}}
        rows.append(row)
        r = locate_key(key)
        why = []
        if r is not None and not r["located"]:
            why.append(f"图块定位不清（ncc {r['ncc']}，第二峰 {r['ncc2']}）")
        elif r is not None and shape is not None and not same_char(r["label"], shape):
            why.append(f"库里图块是「{r['label']}」、本条裁「{shape}」")
        elif r is not None and shape is None:
            why.append("无字裁决，图块只核得了当时入库的那条")
        if r is not None and r["located"] and shape is not None and same_char(r["label"], shape):
            cell = r["cell"]
            al = align.get(cell) if cell is not None else None
            a = {"v": BACKFILL_VERSION, "space": SPACE, "ink_bbox": r["ink_bbox"],
                 "source": "backfill:ink", "product_key": cells_sha}
            if store_patch_fn is not None:
                try:
                    a["content_sha"] = store_patch_fn(r["path"])
                except OSError:
                    pass
            row["anchor"] = a
            row["evidence"] = {"method": "ink", "ncc": r["ncc"], "ncc2": r["ncc2"], "ins": r["ins"],
                               "ins2": r["ins2"], "at": None if cell is None else f"{cell[0]}:{cell[1]}{cell[2]}",
                               "align": al, "ctx": _ctx_word(shape, al)}
            if cell is None:
                row["evidence"]["note"] = "墨跨两格或落空（切开/合并）→ 绑定时回待审"
            continue
        if shape is None:
            row["evidence"] = {"method": None, "reason": "；".join(why) or "无字裁决（seg_defect/not_a_char/skip）且无当时图块，无从核对"}
            continue
        # 上下文：同列 ±2 格里整理本对到的字只有一处是裁的这个字
        _, win = ctx_offset(key, shape)
        ev_sh = [d for s0, d in shift.get(col, []) if abs(s0 - slot) <= 5]
        if len(win) == 1:
            (c, s, sb), ch = win[0]
            off = s - slot
            by_ink = bool(ev_sh) and all(d == off for d in ev_sh)
            by_col = col_shift.get(col) == off and off != 0
            ok = (off == 0 and (c, s, sb) == (col, slot, sub)) or by_ink or by_col
            if (c, s, sb) in idx and ok:
                row["anchor"] = {"v": BACKFILL_VERSION, "space": SPACE, "bbox": idx[(c, s, sb)][0],
                                 "source": "backfill:ctx", "product_key": cells_sha}
                row["evidence"] = {"method": "ctx", "at": f"{c}:{s}{sb}", "align": ch,
                                   "ctx": _ctx_word(shape, ch), "offset": off,
                                   "by": "same" if (off == 0 and (c, s, sb) == (col, slot, sub))
                                   else ("ink_neighbours" if by_ink else "column_consensus"),
                                   "col_shift": sorted(set(ev_sh)),
                                   "col_consensus": [col_shift.get(col), len(col_ctx.get(col, {}))],
                                   "note": "；".join(why) or None}
                continue
            why.append(f"整理本同字在第 {c}:{s}{sb} 格（顺移 {off}），同列旁证：图块 {sorted(set(ev_sh)) or '无'}、"
                       f"上下文 {sorted(col_ctx.get(col, {}).values())}，不足以认定")
        elif not win:
            here = align.get((col, slot, sub))
            why.append("同编号现格已不存在" if (col, slot, sub) not in idx else
                       (f"整理本在本格是「{here}」、±2 格内无「{shape}」" if here else "本格及 ±2 格无整理本对照"))
        else:
            why.append(f"±2 格内整理本有 {len(win)} 处「{shape}」，定不了是哪一格")
        row["evidence"] = {"method": None, "reason": "；".join(why)}
    return rows
