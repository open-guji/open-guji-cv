# -*- coding: utf-8 -*-
"""CV v2 产物 → guji-page v0.2（刻本竖排链）。

只读产物、不写产物：吃 Step1 `border_detect`（版框/界行/列带）、Step3 `row_segment`
（格、抬头、留白）、Step4 `cell_shrink`（字框 `bbox_page`）、Step7 `seed_admit`（定字/通道），
字位流的取字规则**直接复用** `report/slots.page_slots`——与 Step9 的 guji-markdown /
对勘同一份 join，不另写一套（那个模块头记着两套 join 各走各的吃过的亏）。

CV 自己不知道的东西（Book ID、IIIF 册号、IA 原叶号、合扫页拆分的裁切区域、印章框）
由调用方以 `meta` 传入，规范 §3。印章 CV 目前没有产物（自校草案 §七·4），`meta.marks`
里人工给的框会被原样带上，并按几何算出它压住了哪些字框。

v0.2「记录先行」（用户 10-02 裁定 #361·10）：每个字框补 `cand`（各路证据的首位字）与 `channel`
（`seed_admit` 的放行通道），供网站校对模式用。候选取自**已有**产物，缺哪步就缺哪路，不补跑：

| 键 | 来源 | 取法 |
|---|---|---|
| `lib` | Step5-a `glyph_match` | same 档的 `char`，否则 `candidates[0]` |
| `ocr` | Step5-c `ocr_candidates` | `topk[0]` |
| `rare` | Step5-b `rare_candidates` | `candidates[0].char` |
| `ref` | Step5-d `align_ref` | 过闸对齐的 `align_char`，没有则坐标对位的 `ref_char`（非空） |
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.spec import page_key
from ..errors import ProductMissing
from ..products.store import ProductStore
from ..report.slots import cells_step, page_slots
from .guji_page import (LACUNA_CHAR, SCHEMA_ID, canvas_frame, ia_image_id, make_canvas, remap_geometry,
                         seq_for_ws_page, intersects, mint_id, quad_bounds, tr_bbox_to_xywh,
                        tr_point_to_tl, union_xywh)

LANE_OF_KIND = {"char": "main", "jiazhu_a": "jz_r", "jiazhu_b": "jz_l", "jiazhu_solo": "solo"}
STEPS = ("border_detect", "row_segment", "cell_shrink", "seed_admit")


def _candidates(store: ProductStore, book: str, key: str) -> dict[str, dict[str, str]]:
    """字位 id → `{lib, ocr, rare, ref}` 各路首位字（只读已有产物，缺件留空）。"""
    out: dict[str, dict[str, str]] = {}

    def put(cid, k, ch):
        if ch:
            out.setdefault(cid, {})[k] = ch

    gm = store.read(book, "glyph_match", key, "glyph_match")
    for col in (gm.columns if gm else []):
        for r in col.chars:
            put(r.id, "lib", r.char if r.verdict == "same" and r.char else
                (r.candidates[0][0] if r.candidates else None))
    ocr = store.read(book, "ocr_candidates", key, "ocr_candidates")
    for col in (ocr.columns if ocr else []):
        for r in col.chars:
            put(r.id, "ocr", r.topk[0][0] if r.topk else None)
    rare = store.read(book, "rare_candidates", key, "rare_candidates")
    for col in (rare.columns if rare else []):
        for r in col.chars:
            put(r.id, "rare", r.candidates[0].char if r.candidates else None)
    ar = store.read(book, "align_ref", key, "align_ref")
    if ar:
        for r in ar.coord:
            put(r.id, "ref", r.ref_char)
        for r in ar.chars:                    # 过闸对齐优先于坐标对位
            if r.align_char:
                out.setdefault(r.id, {})["ref"] = r.align_char
    return out


def _manifest_row(store: ProductStore, book: str, step: str, key: str) -> dict | None:
    """该步该页 `_manifest.jsonl` 里最后一条记录（指纹、上游 sha、code_rev）。"""
    p = store.step_dir(book, step) / "_manifest.jsonl"
    if not p.exists():
        return None
    row = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if f'"{key}"' not in line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("key") == key:
            row = d
    return row


def _rules(borders, W: int) -> list[list[list[int]]]:
    """界行折线（左上原点整数点列）：在上/下内框之间按折点取样。"""
    out = []
    for v in borders.verticals:
        vl = v.to_vline()
        xr = (W - 1) / 2.0
        y_top = borders.top.to_hline().y_at(xr)
        y_bot = borders.bottom.to_hline().y_at(xr)
        ys = [y_top] + [y for y in (v.y1, v.y2) if y is not None and y_top < y < y_bot] + [y_bot]
        out.append([tr_point_to_tl((float(vl.x_at(y)), y), W) for y in ys])
    return out


def from_cv_products(store: ProductStore, book: str, page: int, meta: dict,
                     glyph_ids: dict[str, str] | None = None) -> dict:
    """`glyph_ids`：字位 id → 刻例 id（查字形库 instances 得来）。CV 总管 §八·2 定了两者
    「格式同构、值不保证相等」，所以不传就一律记 null，**不拿字位 id 冒充**。"""
    glyph_ids = glyph_ids or {}
    key = page_key(page)
    bd = store.read_raw(book, "border_detect", key)
    if bd is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 border_detect 产物")
    from ..products.kinds.borders import Borders
    borders = Borders.model_validate(bd["borders"])
    W, H = borders.width, borders.height
    lines = (bd.get("line_index") or {}).get("lines") or []

    cstep = cells_step(book)
    cells = store.read(book, cstep, key, "cells")
    chars = store.read(book, "cell_shrink", key, "char_index")
    if cells is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {cstep} 产物")
    stale: list[str] = []
    slots = page_slots(store, book, page, stale)
    admit_raw = store.read(book, "seed_admit", key, "seed_admit")
    admit_by_id = {r.id: r for c in admit_raw.columns for r in c.chars} if admit_raw else {}
    cands = _candidates(store, book, key)

    # ── 图像与来历 ──
    rows = {s: _manifest_row(store, book, s, key) for s in STEPS}
    raw_sha = ((rows.get("border_detect") or {}).get("upstream") or {}).get("raw_page")
    m_img = dict(meta.get("image") or {})
    image = {"width": W, "height": H, "sha256": raw_sha}
    for k in ("path", "source", "region", "edits", "note"):
        if m_img.get(k) is not None:
            image[k] = m_img[k]
    if m_img.get("sha256") and raw_sha and m_img["sha256"] != raw_sha:
        image["note"] = ((image.get("note") or "") +
                         f"｜坐标所在的图是 CV 跑批时的 {raw_sha[:12]}，"
                         f"不是 meta 给的 {m_img['sha256'][:12]}——换图要经 region 换算").lstrip("｜")
    cells_sha = (rows.get("row_segment") or {}).get("sha256") or ""
    producers = {
        "cv": {"tool": "open-guji-cv",
               "rev": (rows.get("seed_admit") or {}).get("code_rev"),
               "pipeline": meta.get("pipeline", "keben_body_v2"),
               "steps": {s: (rows[s] or {}).get("code_rev") for s in STEPS if rows.get(s)},
               "products_sha": {s: (rows[s] or {}).get("sha256") for s in STEPS if rows.get(s)}},
    }
    if meta.get("snapshot"):
        producers["cv"]["snapshot"] = meta["snapshot"]
    for pk, pv in (meta.get("producers") or {}).items():
        producers[pk] = pv

    page_id = f"{meta['book']['id']}/{meta['volume']['index']}/{meta['page']['index']}"

    # ── 字框几何 ──
    box_by_id: dict[str, list[int]] = {}
    if chars is not None:
        for col in chars.columns:
            for ch in col.chars:
                if ch.bbox_page is not None and ch.cell_type != "empty":
                    box_by_id[ch.id] = tr_bbox_to_xywh(ch.bbox_page, W)
    quad_by_key: dict[tuple[int, int, str], list] = {}
    for col in cells.columns:
        for c in col.cells:
            if c.quad_page:
                quad_by_key[(col.col, c.slot, c.sub or "")] = c.quad_page

    def cell_box(col: int, slot: int, sub: str | None):
        q = quad_by_key.get((col, slot, sub or ""))
        return tr_bbox_to_xywh(quad_bounds(q), W) if q else None

    # ── 文本流、列、字框、标记 ──
    text: list[str] = []
    lacuna: list[int] = []
    glyphs: list[dict] = []
    marks: list[dict] = []
    columns: list[dict] = []
    slots_by_col: dict[int, list] = {}
    for s in slots:
        slots_by_col.setdefault(s.col, []).append(s)
    line_by_col = {ln["col"]: ln for ln in lines}

    for col_cells in sorted(cells.columns, key=lambda c: c.col):
        cn = col_cells.col
        cid = f"c{cn}"
        ln = line_by_col.get(cn)
        col_box = tr_bbox_to_xywh((ln["x0"], ln["y0"], ln["x1"], ln["y1"]), W) if ln else None
        lead = 0
        by_key = {(c.slot, c.sub or ""): c for c in col_cells.cells}
        sl = 1
        while by_key.get((sl, "")) is not None and by_key[(sl, "")].kind == "blank":
            lead += 1
            sl += 1
        col = {"id": cid, "n": cn, "kind": (ln or {}).get("kind", "body"), "box": col_box,
               "raised": col_cells.n_raised, "lead_blank": lead, "runs": []}
        if not col_cells.ok:
            col["note"] = f"Step3 无解：{col_cells.error}"
        for c in col_cells.cells:
            if c.kind == "blank":
                marks.append({"id": mint_id("m", page_id, f"{book}:{page}:{cn}:{c.slot}{c.sub or ''}", "blank"),
                              "kind": "blank", "col": cid, "slot": c.slot,
                              "box": cell_box(cn, c.slot, c.sub), "by": "cv"})
        for s in slots_by_col.get(cn, []):
            box = box_by_id.get(s.id) or cell_box(cn, s.slot, s.sub)
            if s.excluded:
                marks.append({"id": mint_id("m", page_id, s.id, cells_sha), "kind": "excluded",
                              "col": cid, "slot": s.slot, "box": box, "by": "cv",
                              "cv_id": s.id, "note": "排除名单·非字（墨污/切坏）"})
                continue
            lane = LANE_OF_KIND.get(s.kind, "main")
            i = len(text)
            if s.char is None:                 # 不知道原字：v0.2 写可见的「□」并记进页上 lacuna
                text.append(LACUNA_CHAR)
                lacuna.append(i)
            else:
                text.append(s.char)
            runs = col["runs"]
            if runs and runs[-1]["lane"] == lane and runs[-1]["text"][1] == i:
                runs[-1]["text"][1] = i + 1
            else:
                runs.append({"lane": lane, "text": [i, i + 1]})
            rec = admit_by_id.get(s.id)
            ev = (rec.evidence if rec else {}) or {}
            occ = bool(ev.get("occluded"))
            if s.admit and s.human:
                method, review = "human", "human"
            elif s.admit:
                method, review = f"cv:{s.channel}", "auto"
            elif occ and s.char:
                method, review = "cv:occluded_default", "pending"
            else:
                method, review = "cv:pending", "pending"
            g = {"id": mint_id("g", page_id, s.id, cells_sha), "text": [i, i + 1],
                 "box": box, "col": cid, "lane": lane, "slot": s.slot,
                 "cv_id": s.id, "glyph_id": glyph_ids.get(s.id),
                 "by": {"box": "cv" if box else None, "text": "cv"},
                 "method": method, "review": review, "conf": None, "channel": s.channel}
            if cands.get(s.id):
                g["cand"] = {k: cands[s.id][k] for k in ("lib", "ocr", "rare", "ref") if k in cands[s.id]}
            if box and s.id not in box_by_id:
                g["box_from"] = "cell_quad"
            if s.unreadable:
                g["lacuna"] = "unreadable"
            elif s.defect:
                g["lacuna"] = "defect"
            if s.guess:
                g["guess"] = s.guess
            flags = []
            if occ:
                flags.append("occluded")
            if flags:
                g["flags"] = flags
            cv = {"channel": s.channel, "doubts": s.doubts}
            if "cov" in ev:
                cv["cov"] = ev["cov"]
            g["ext"] = {"cv": cv}
            glyphs.append(g)
        columns.append(col)

    region = {"id": "r1", "kind": "body",
              "box": union_xywh(c["box"] for c in columns if c.get("box")),
              "rules": _rules(borders, W), "columns": columns}

    # meta 给的非字元素（印章、版心、页码……）：原样带上，算出压到的字框
    for k, m in enumerate(meta.get("marks") or []):
        mm = dict(m)
        mm.setdefault("id", mint_id("m", page_id, "meta", str(k), json.dumps(m, sort_keys=True)))
        mm.setdefault("by", "manual")
        if mm.get("kind") == "seal" and mm.get("box"):
            mm["occludes"] = [g["id"] for g in glyphs if g.get("box") and intersects(g["box"], mm["box"])]
        marks.append(mm)

    page_obj = {
        "schema": SCHEMA_ID,
        "page_id": page_id,
        "book": meta["book"],
        "volume": meta["volume"],
        "page": meta["page"],
        "image": image,
        "canvas": None,
        "producers": producers,
        "text": text,
        "lacuna": lacuna,
        "norm": list(meta.get("norm") or []),
        "zi": list(meta.get("zi") or []),
        "regions": [region],
        "glyphs": glyphs,
        "marks": marks,
    }
    warnings = [f"Step3/Step7 对不上（产物过期）：{x}" for x in stale]
    page_obj["canvas"] = _canvas(meta, page, image, warnings, page_obj)
    if warnings:
        page_obj["warnings"] = warnings
    return page_obj


def _canvas(meta: dict, page: int, image: dict, warnings: list, page_obj: dict) -> dict:
    """定 canvas（网站总管 #357 约定），必要时把几何从 CV 跑批那张图搬到 canvas 上。

    - `meta.canvas` 显式给了就用它；
    - 否则按 `meta.split_rows`（该册在整理总管「合扫拆页裁剪框」表里的行）把工作区页号换成页序：
      拆块页 canvas = 裁剪框（`source.selector`），其余 canvas = 整张原叶 = 本页图；
    - CV 跑批那张图的帧（`image.region`）与 canvas 帧不同 → `remap_geometry` 搬过去并记一条 warning。
    """
    book_id, vol = meta["book"]["id"], int(meta["volume"]["index"])
    item = meta["volume"].get("ia_item")
    W, H = image["width"], image["height"]
    if meta.get("canvas"):
        c = dict(meta["canvas"])
        if c.get("seq") and not c.get("id"):
            from .guji_page import canvas_id
            c["id"] = canvas_id(book_id, vol, c["seq"])
    else:
        seq, row = seq_for_ws_page(page, meta.get("split_rows"))
        if row:
            c = make_canvas(book_id, vol, seq, width=row["xywh"][2], height=row["xywh"][3],
                            source_id=ia_image_id(item, row["ia_leaf"]) if item else None,
                            source_size=row["orig_size"], xywh=row["xywh"])
        else:
            c = make_canvas(book_id, vol, seq, width=W, height=H)
    dst = canvas_frame(c)
    reg = image.get("region")
    if reg is None:
        if (W, H) != (dst["width"], dst["height"]):
            warnings.append(f"CV 跑批的图 {W}×{H} 与 canvas {dst['width']}×{dst['height']} 尺寸不同、"
                            "又没给 image.region，坐标没法换到 canvas——按原样保留，需人核")
        elif dst.get("region"):
            image["region"] = list(dst["region"])          # 跑批的图就是这一块：region ⇔ selector
        return c
    src = {"width": W, "height": H, "region": reg,
           "source": {"width": (image.get("source") or {}).get("width"),
                      "height": (image.get("source") or {}).get("height")}}
    if dst.get("region") is None:
        dst = dict(dst, region=[0, 0, dst["width"], dst["height"]])
    if [float(v) for v in reg] != [float(v) for v in dst["region"]] or (W, H) != (dst["width"], dst["height"]):
        had = {g["id"] for g in page_obj["glyphs"] if g.get("box")}
        n = remap_geometry(page_obj, src, dst)
        lost = [g["cv_id"] for g in page_obj["glyphs"] if g["id"] in had and not g.get("box")]
        warnings.append(f"坐标已从 CV 跑批的图（原叶上 xywh={','.join(map(str, reg))}）换到 canvas "
                        f"{c.get('seq')}（xywh={','.join(map(str, dst['region']))}），裁到 canvas 内 {n} 个框"
                        + (f"；整个落在 canvas 外、box 置 null 的字框 {len(lost)} 个：{','.join(lost)}" if lost else ""))
    return c


def export_page(products_root: Path | str | None, book: str, page: int, meta: dict,
                glyph_ids: dict[str, str] | None = None) -> dict:
    store = ProductStore(Path(products_root)) if products_root else ProductStore()
    return from_cv_products(store, book, page, meta, glyph_ids)
