# -*- coding: utf-8 -*-
"""审阅卡的「相似字」候选 `alt`：近似字的异体族按字块图排序（只出候选，不进放行）。

用户 2026-10-19：人审最花时间的是找最接近的字——先认出一个近似字，再去字统网翻它的一大批
异体，挑和图最像的。这里替人把这一趟做掉：

1. **近似字（pivot）**从卡上取，按优先级：整理本字 → 本书惯刻形 → 上下文字 → 库前 3 →
   义定形未定的组内形 → 己已巳建议 → 引擎定的字；`extra_pivots` 可再追加（如 5-b 前几名）。
2. **池子**＝各近似字的异体族（自建汉字关系库 `hanzi`，本机字统网缓存照并）＋形近表，见
   `clustering.variant_sources.family_pool`。
3. **排序**＝字块图与各字字体模板的 CNN embedding 余弦（与 5-b 同一个模型、同一套模板），
   离线读数：近似字一跳族按图排 top-3 413/414，不排序 top-5 只有 353（研究文档 §4.2）。

全部在出待审单时算好，写进卡片 `alt` 字段，经 `proof_fields.pending_fields` 进 pending.json，
随中心库 → COS 发到网站；网站和控制台只显示，不现算。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

ALT_K = 30                    # 每格最多给几个
ALT_SHOW = 10                 # 前端缺省展开几个（用户 10-19 定）
#: 字块图与某个特殊符号模板的余弦 ≥ 这个值，就把符号表并进池子（设计 4.3 兜底）。
#: 10-21 在殿本 vol04–10 待审 1255 格上扫：真符号格（○×4、⊙×1）0.94–0.97，其余最高 0.84
SYM_MIN = 0.93


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
    向量逐位相同；但只算池子里出现的字（一册几千字），不建 7 万字大索引。
    本机已有与现役模型同规格的全字表向量包（`clustering.emb_pack`，`guji cache pull-rare-index` 拉）
    就直接取行，不现场渲染；包是同一个函数建的，逐位相同。"""

    def __init__(self, cnn=None, use_pack: bool = True):
        if cnn is None:
            from ..clustering.cnn_candidates import shared
            cnn = shared()
        self.cnn = cnn
        self._vec: dict[str, np.ndarray | None] = {}
        self._pack = None
        if use_pack:
            try:
                from ..clustering.cnn_candidates import DEFAULT_CKPT
                from ..clustering.emb_pack import load_current
                if Path(cnn.ckpt).resolve() == Path(DEFAULT_CKPT).resolve():
                    self._pack = load_current(download=False)
            except (OSError, ValueError, KeyError, ImportError, AttributeError):
                self._pack = None

    @property
    def available(self) -> bool:
        return bool(self.cnn._ensure())

    def vectors(self, chars: list[str]) -> dict[str, np.ndarray]:
        todo = [c for c in chars if c not in self._vec]
        if todo and self._pack is not None:
            got = self._pack.vectors(todo)
            self._vec.update(got)
            todo = [c for c in todo if c not in got and c not in self._pack.failed]
            self._vec.update({c: None for c in chars if c in self._pack.failed})
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


def symbol_hint(q: np.ndarray, vectors: Callable[[list[str]], dict[str, np.ndarray]],
                beat: float = -1.0) -> str | None:
    """字块图像不像某个特殊符号：最像的那个符号余弦 ≥ `SYM_MIN`、且高过 `beat`（这格自己池子里
    最像的字）才返回它，否则 None。只看绝对值不够：曰、日 的字块和 □ 的余弦也能过 0.93，
    但比不过 曰、日 本身（10-21 殿本扫描）。"""
    from ..hanzi.symbols import symbols
    vec = vectors(list(symbols()))
    best = max(((float(v @ q), c) for c, v in vec.items()), default=(0.0, None))
    return best[1] if best[0] >= SYM_MIN and best[0] > beat else None


def _with_symbols(q, pivots: list[str], bank, zi, k: int) -> list[dict]:
    """池子按图排序；图像比池子里最像的字更像某个符号时，符号表并进池子再排（设计 4.3）。"""
    from ..clustering.variant_sources import family_pool
    pool = family_pool(pivots, zi=zi)
    ranked = rank_pool(q, pool, bank.vectors, k) if pool else []
    sym = symbol_hint(q, bank.vectors, beat=ranked[0]["s"] if ranked else -1.0)
    if sym:
        ranked = rank_pool(q, family_pool(pivots + [sym], zi=zi), bank.vectors, k)
    return ranked


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
    if q is None:
        return []
    return _with_symbols(q, pivots, bank, zi, k)


_BANK: TemplateBank | None = None


def shared_bank() -> TemplateBank:
    """进程内共用一个模板库（控制台常驻，查过的字的模板向量一直留着）。"""
    global _BANK
    if _BANK is None:
        _BANK = TemplateBank()
    return _BANK


def alt_for_cards(book: str, cards: list[dict], *, k: int = ALT_K, zi=None, bank: TemplateBank | None = None,
                  extra_pivots: dict[str, list[str]] | None = None, image_cache=None, ctx=None,
                  log: Callable[[str], None] | None = None) -> dict[str, list[dict]]:
    """一批卡 → `{卡 id: alt 列表}`。取不到字块图、或 CNN 不可用的卡不出（键缺席）。

    给了 ``ctx``（`RunContext`）时，缓存里没有的字块图从原图＋cell_shrink 现切（`ctx.image`）：
    从产物包出单（`republish.py from-pack`）只有 products、没有 cache/，不现切就一格都取不到图，
    10-21 殿本 vol04–10 重发的待审单因此整批没有相似字。"""
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
    no_img = 0
    for i, c in enumerate(cards):
        img = rare_patch(book, int(c["page"]), int(c["col"]), int(c["slot"]), c.get("sub") or "", image_cache)
        if img is None and ctx is not None:
            key = f"p{int(c['page']):04d}c{int(c['col']):02d}s{int(c['slot'])}{c.get('sub') or ''}"
            try:
                img = ctx.image("char_patch", key)
            except Exception:  # noqa: BLE001 — 切不出就当没图，与缓存缺图同口径
                img = None
        if img is None:
            no_img += 1
            continue
        q = bank.embed(normalize_patch(img, stroke_width=ns))
        if q is None:
            continue
        piv = pivots_of(c, (extra_pivots or {}).get(c["id"], ()))
        ranked = _with_symbols(q, piv, bank, zi, k)
        if ranked:
            out[c["id"]] = ranked
        if log and (i + 1) % 100 == 0:
            log(f"alt：{i + 1}/{len(cards)} 格")
    if log and no_img:
        log(f"alt：{no_img}/{len(cards)} 格取不到字块图，没出相似字")
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


def _old_cands(card: dict) -> list[str]:
    """卡上原有的几路候选（整理本字、上下文字、库前 3、己已巳）——相似字上线前人能直接点的那些。"""
    out: list[str] = []
    for c in [(card.get("ref") or {}).get("char"), (card.get("ctx") or {}).get("char")] + \
             [x[0] if isinstance(x, (list, tuple)) else (x or {}).get("c")
              for x in ((card.get("db") or {}).get("candidates") or [])[:3]] + \
             [(card.get("jys") or {}).get("char") if isinstance(card.get("jys"), dict) else card.get("jys")]:
        if isinstance(c, str) and len(c) == 1 and c not in out:
            out.append(c)
    return out


def alt_eval(cards: list[dict], human: dict[str, str]) -> dict:
    """人裁字 vs 卡上 alt：两个指标——前 5／10 名里有没有人最后定的字（召回），排第几（首位率、平均名次）。

    `human`＝`{格 id: 人定的字}`（`feedback.lookup.human_chars`）。只算带 alt、有人裁字的卡。
    分两档报：**全部**，和**难格**（人定的字不在卡上原有候选里——相似字上线前只能手输或去字统网查的那些）。"""
    def tier(rows: list[tuple[str, list[str], list[str]]]) -> dict:
        n = len(rows)
        ranks = [alt.index(g) + 1 if g in alt else None for g, alt, _ in rows]
        hit = [r for r in ranks if r]
        return {"n": n, **{f"top{k}": sum(1 for r in ranks if r and r <= k) for k in (1, 3, 5, 10)},
                "in_alt": len(hit), "mean_rank_when_hit": round(sum(hit) / len(hit), 2) if hit else None}

    rows, hard = [], []
    for c in cards:
        alt = [a["c"] for a in c.get("alt") or ()]
        g = human.get(c.get("id", ""))
        if not alt or not g:
            continue
        old = _old_cands(c)
        rows.append((g, alt, old))
        if g not in old:
            hard.append((g, alt, old))
    return {"all": tier(rows), "hard": tier(hard),
            "hard_examples": [{"g": g, "rank": (alt.index(g) + 1 if g in alt else None), "old": "".join(old)}
                              for g, alt, old in hard[:30]]}
