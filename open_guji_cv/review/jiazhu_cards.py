# -*- coding: utf-8 -*-
"""夹注**段**卡的装配：一张卡 = 一段雙行小注，不是一格一张。

从 `console/app.py::api_jiazhu_segments` 搬来（控制台重构 C2）。装配逻辑一行未改，
只动了函数名、`ProductStore`／`EventLog` 改成可注入、延迟 import 提到模块级。
"""
from __future__ import annotations

from ..core.book import load_book
from ..core.spec import cell_key, page_key
from ..feedback.events import EventLog
from ..gold.v2_align import align_book
from ..products.store import ProductStore
from ..utils.jiazhu_order import segments as jz_segments
from ..utils.jiazhu_order import sort_by_reading


def jiazhu_segments(book: str = "vol02", pages: str = "jz",
                    only: str = "all", batch: str | None = None,
                    store: ProductStore | None = None,
                    log: EventLog | None = None) -> dict:
    """夹注**段**卡：一张卡 = 一段雙行小注，不是一格一张。

    一段版本注 5–19 字，人一眼能读整句；逐格出卡等于把一句话拆成十几道题，
    既慢又看不出「这段到底通不通」。所以段是审阅单位：列条裁图 + a/b 两串
    并排 + 整理本对应注文，三个动作（整段确认 / 改某一格 / 标切分缺陷）。

    `only`：all（默认）| review 只出含待审格的段 | auto 只出全自动的段（抽查用）。
    抽查自动段与 `/api/review/cards` 的 `only=auto` 同理——只看待审的那批，
    永远只能证明「拿不准的确实拿不准」。
    """
    st = store or ProductStore()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)
    try:
        golds = {c.id: c for g in align_book(book, pgs, st) if g.anchored for c in g.chars}
    except Exception:
        golds = {}
    done: dict[str, dict] = {}
    if batch:
        for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
            if e.kind in ("confirm", "seg_defect"):
                done[e.target.key] = dict(e.payload)

    out: list[dict] = []
    for pg in pgs:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if a is None:
            continue
        cellmap = {}
        for c in (cells.columns if cells else []):
            for cell in c.cells:
                cellmap[(c.col, cell.slot, cell.sub or "")] = cell
        for cc in a.columns:
            jz = [r for r in cc.chars if r.sub]
            if not jz:
                continue
            for seg in jz_segments((r.slot, r.sub) for r in jz):
                sset = set(seg)
                rs = sort_by_reading([r for r in jz if r.slot in sset])
                if not rs:
                    continue
                ys = [cellmap.get((cc.col, r.slot, r.sub or ""))
                      for r in rs]
                ys = [c for c in ys if c is not None]
                if not ys:
                    continue
                y0 = int(min(c.y0 for c in ys)) - 30
                y1 = int(max(c.y1 for c in ys)) + 30
                cellsjs = []
                for r in rs:
                    g = golds.get(r.id)
                    cell = cellmap.get((cc.col, r.slot, r.sub or ""))
                    cellsjs.append({
                        "id": r.id, "slot": r.slot, "sub": r.sub,
                        "char": r.char, "admit": r.admit, "channel": r.channel,
                        "ref": g.reading if g else None,
                        "patch": (f"/api/cache/{book}/char_patch/"
                                  f"{cell_key(pg, cc.col, r.slot)}{r.sub or ''}.png"),
                        "done": done.get(r.id),
                        # 型 1 疑似标记（jiazhu_split.suspect_full_width_cells）：
                        # 这一格可能是被缝位骗过的整宽正文字，不是真夹注。
                        # 只标记不改切分，人工审查用。
                        "suspect": bool(cell and cell.suspect_jiazhu_body),
                    })
                n_rev = sum(1 for r in rs if not r.admit)
                n_suspect = sum(1 for c in cellsjs if c["suspect"])
                if only == "review" and not n_rev:
                    continue
                if only == "auto" and n_rev:
                    continue
                a_txt = "".join(c["char"] or "□" for c in cellsjs if c["sub"] == "a")
                b_txt = "".join(c["char"] or "□" for c in cellsjs if c["sub"] == "b")
                ref_txt = "".join(c["ref"] or "·" for c in cellsjs)
                out.append({
                    "id": f"{book}:{pg}:{cc.col}:{seg[0]}",
                    "book": book, "page": pg, "col": cc.col,
                    "slots": seg, "n": len(rs), "n_review": n_rev,
                    "n_suspect": n_suspect,
                    "a": a_txt, "b": b_txt, "text": a_txt + b_txt,
                    "ref": ref_txt,
                    "img": (f"/api/cutline/img/{book}/{pg}/{cc.col}.png"
                            f"?y0={max(0, y0)}&y1={y1}"),
                    "cells": cellsjs,
                })
    return {"book": book, "pages": pgs, "n": len(out),
            "n_review": sum(1 for s in out if s["n_review"]),
            "n_suspect": sum(1 for s in out if s["n_suspect"]), "segments": out}
