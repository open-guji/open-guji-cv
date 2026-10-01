# -*- coding: utf-8 -*-
"""离线：从已落盘的产物（`ProductStore`）还原每格的 `CellEvidence`（评估／对账用，不读图）。

线上 `seed_admit._shadow_veto_pass` 读的是同样的上游产物（glyph_match / rare_candidates / align_ref），
这里按同一取法读盘，供 `scripts/shadow_gate_eval.py` 与口径对账测试使用。
"""
from __future__ import annotations

from .signals import CellEvidence


def page_evidence(st, book: str, page: int) -> dict[str, CellEvidence]:
    """一页 → {字位: CellEvidence}；现字取 `seed_admit` 产物里的 char（放行字／待审默认字）。"""
    from ..core.spec import page_key
    key = page_key(page)
    gm = {r["id"]: r for c in st.read(book, "glyph_match", key, "glyph_match").model_dump()["columns"]
          for r in (c.get("chars") or [])}
    rc: dict = {}
    if st.exists(book, "rare_candidates", key):
        rc = {r["id"]: r for c in st.read(book, "rare_candidates", key, "rare_candidates").model_dump()["columns"]
              for r in (c.get("chars") or [])}
    al = {r["id"]: r for r in st.read(book, "align_ref", key, "align_ref").model_dump()["chars"]}
    sa = {r["id"]: r for c in st.read(book, "seed_admit", key, "seed_admit").model_dump()["columns"]
          for r in (c.get("chars") or [])}
    out = {}
    for i, rec in sa.items():
        g = gm.get(i) or {}
        out[i] = CellEvidence(
            id=i, lib=[(c, v) for c, v in (g.get("candidates") or [])],
            rare=[(x["char"], x["score"]) for x in ((rc.get(i) or {}).get("candidates") or [])],
            ref=(al.get(i) or {}).get("align_char"), cur=rec.get("char"))
    return out
