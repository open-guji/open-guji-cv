# -*- coding: utf-8 -*-
"""审阅卡的「相似字」候选 `alt`：近似字的异体族按字块图排序（只出候选，不进放行）。

用户 2026-10-19：人审最花时间的是找最接近的字——先认出一个近似字，再去字统网翻它的一大批
异体，挑和图最像的。这里替人把这一趟做掉：

1. **近似字（pivot）**从卡上取，按优先级：整理本字 → 本书惯刻形 → 上下文字 → 库前 3 →
   义定形未定的组内形 → 己已巳建议 → 引擎定的字；`extra_pivots` 可再追加（如 5-b 前几名）。
2. **池子**＝各近似字的异体族（本仓表、部件檢索、字统网缓存）＋形近表，见
   `clustering.variant_sources.family_pool`。
3. **排序**＝字块图与各字字体模板的 CNN embedding 余弦（与 5-b 同一个模型、同一套模板），
   离线读数：近似字一跳族按图排 top-3 413/414，不排序 top-5 只有 353（研究文档 §4.2）。

全部在出待审单时算好，写进卡片 `alt` 字段，经 `proof_fields.pending_fields` 进 pending.json，
随中心库 → COS 发到网站；网站和控制台只显示，不现算。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np

ALT_K = 30                    # 每格最多给几个
ALT_SHOW = 10                 # 前端缺省展开几个（用户 10-19 定）


def pivots_of(card: dict, extra: Iterable[str] = ()) -> list[str]:
    """卡 → 近似字列表（去重保序）。"""
    out: list[str] = []

    def put(c) -> None:
        if isinstance(c, str) and len(c) == 1 and c not in out:
            out.append(c)

    ref = card.get("ref") or {}
    put(ref.get("char"))
    put(ref.get("form"))
    ctx = card.get("ctx") or {}
    put(ctx.get("char"))
    put(ctx.get("llm_suggestion"))
    for cand in ((card.get("db") or {}).get("candidates") or [])[:3]:
        put(cand[0] if isinstance(cand, (list, tuple)) else (cand or {}).get("c"))
    for f in ((card.get("form") or {}).get("forms") or []):
        put(f if isinstance(f, str) else (f or {}).get("char"))
    jys = card.get("jys")
    put(jys.get("char") if isinstance(jys, dict) else jys)
    put((card.get("occluded") or {}).get("char"))
    put(card.get("char"))
    for c in extra:
        put(c)
    return out


class TemplateBank:
    """字 → 字体模板 embedding（单位向量），按字记忆化。

    与 5-b 的 `_emb_index` 同一个函数（`cnn_candidates.build_emb_matrix`）算，所以同一个字两边的
    向量逐位相同；但只算池子里出现的字（一册几千字），不建 7 万字大索引。"""

    def __init__(self, cnn=None):
        if cnn is None:
            from ..clustering.cnn_candidates import shared
            cnn = shared()
        self.cnn = cnn
        self._vec: dict[str, np.ndarray | None] = {}

    @property
    def available(self) -> bool:
        return bool(self.cnn._ensure())

    def vectors(self, chars: list[str]) -> dict[str, np.ndarray]:
        todo = [c for c in chars if c not in self._vec]
        if todo:
            from ..clustering.cnn_candidates import build_emb_matrix
            from ..clustering.synth import render_char
            mat, names = build_emb_matrix(self.cnn._net, self.cnn._dev, tuple(todo), {}, render_char)
            got = dict(zip(names, mat))
            for c in todo:
                self._vec[c] = got.get(c)
        return {c: self._vec[c] for c in chars if self._vec.get(c) is not None}

    def embed(self, norm_patch: np.ndarray) -> np.ndarray | None:
        e = self.cnn.embed([norm_patch])
        return e[0] if len(e) else None


def rank_pool(q: np.ndarray, pool: dict[str, dict], vectors: Callable[[list[str]], dict[str, np.ndarray]],
              k: int = ALT_K) -> list[dict]:
    """池子按与 q 的余弦排序 → `[{c, s, p, src}]`（前 k 个）。渲染不出模板的字排不了，丢掉。"""
    vec = vectors(list(pool))
    scored = sorted(((float(v @ q), c) for c, v in vec.items()), key=lambda t: (-t[0], t[1]))
    return [{"c": c, "s": round(s, 4), "p": pool[c]["p"], "src": pool[c]["src"]} for s, c in scored[:k]]


def alt_for_image(book: str | None, img, pivots: list[str], *, k: int = ALT_K, zi=None,
                  bank: TemplateBank | None = None) -> list[dict]:
    """一张字块图 ＋ 近似字 → alt 列表（控制台现场查一格用；出待审单批量走 `alt_for_cards`）。"""
    from ..clustering.normalize import normalize_patch
    from ..clustering.rare_panel import _book_norm_stroke
    from ..clustering.variant_sources import family_pool

    bank = bank or shared_bank()
    if img is None or not bank.available:
        return []
    q = bank.embed(normalize_patch(img, stroke_width=_book_norm_stroke(book)))
    pool = family_pool(pivots, zi=zi)
    return rank_pool(q, pool, bank.vectors, k) if (q is not None and pool) else []


_BANK: TemplateBank | None = None


def shared_bank() -> TemplateBank:
    """进程内共用一个模板库（控制台常驻，查过的字的模板向量一直留着）。"""
    global _BANK
    if _BANK is None:
        _BANK = TemplateBank()
    return _BANK


def alt_for_cards(book: str, cards: list[dict], *, k: int = ALT_K, zi=None, bank: TemplateBank | None = None,
                  extra_pivots: dict[str, list[str]] | None = None, image_cache=None,
                  log: Callable[[str], None] | None = None) -> dict[str, list[dict]]:
    """一批卡 → `{卡 id: alt 列表}`。取不到字块图、或 CNN 不可用的卡不出（键缺席）。"""
    from ..clustering.normalize import normalize_patch
    from ..clustering.rare_panel import _book_norm_stroke, rare_patch
    from ..clustering.variant_sources import family_pool

    bank = bank or TemplateBank()
    if not bank.available:
        if log:
            log("CNN 不可用（缺 torch 或 checkpoint），不出 alt")
        return {}
    ns = _book_norm_stroke(book)
    out: dict[str, list[dict]] = {}
    for i, c in enumerate(cards):
        img = rare_patch(book, int(c["page"]), int(c["col"]), int(c["slot"]), c.get("sub") or "", image_cache)
        if img is None:
            continue
        q = bank.embed(normalize_patch(img, stroke_width=ns))
        if q is None:
            continue
        piv = pivots_of(c, (extra_pivots or {}).get(c["id"], ()))
        pool = family_pool(piv, zi=zi)
        if pool:
            out[c["id"]] = rank_pool(q, pool, bank.vectors, k)
        if log and (i + 1) % 100 == 0:
            log(f"alt：{i + 1}/{len(cards)} 格")
    return out


def attach(cards: list[dict], alt: dict[str, list[dict]]) -> int:
    """把 alt 挂到卡上（`card["alt"]`），返回挂了几张。"""
    n = 0
    for c in cards:
        a = alt.get(c.get("id"))
        if a:
            c["alt"] = a
            n += 1
    return n
