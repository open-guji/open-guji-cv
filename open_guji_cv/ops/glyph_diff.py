"""字形库换版后 Step5-a 只重算受影响的格：kNN 邻域差分（2026-10-24，A23）。

## 为什么

`glyph_match` 的库指纹是软参数（见该模块头「库指纹：记录，不判过期」）：库变了不判过期，要吃新库得
`guji recheck` 点名。现成的点名口径太粗：`--chars` 按「记录里出现过变了的字」点，可每格存了前 10 个候选，
「十、人、而」这类常用字一进新刻例就把三分之一的格牵进来（殿本 vol04/vol08 实测 g1 之后 239 个字头命中
32–35%）；`--verdicts unsure,diff` 约半价。

## 怎么判

5a 慢在逐对弹性精验（每页约 12 秒）；粗排的 HOG 特征加 kNN 只要几毫秒。一格的判决只取决于库里这几样，
旧库、新库各算一遍、比一比，任一条不同才点名：

1. `knn`：本格（及它的候选试切）在库里的前 k 个邻居——刻本库一份、整库一份（`font_tier` 两档都可能用到），
   按 (条目 id, 字头, 归一图摘要) 逐位比，**连顺序**；摘自身（`_same_cell_rows`）与 5a 同口径；
2. `dead`：same 档命中的条目在新库里已撤或改了字头（同 `recheck --dead`）；
3. `consensus`：候选字的人裁例数跨过共识升档门槛（`consensus_min_confirmed`）；已经按共识升档的格，那个字的例数
   一变就算（产物里 `via` 记着例数）；
4. `near_shape`：开了近形决胜、记录里那一对字的刻例（含是否人裁）变了；
5. `shape_rerank`：开了形区分四对、候选里有那 8 个字且刻例变了；
6. `borrow`：借来的条目集合变了（整格点名）；`timeout` 格一律点名。

五条都没变的格，5a 拿到的输入（同一张图、同一组邻居、同样的升档条件）与上次相同，旧记录可以照搬。
护栏 1 的「对家在不在库里」缺省不看库（`guard_needs_partner_in_db`），所以不用比；`GUJI_GUARD_IN_DB=1`
时把字集变化也算进 `knn` 那条之外的点名（`partner`）。

相似度按 5a 的 `batch_knn` 同一种算法（整页按 64 个一块做矩阵乘）算，以免逐格算与合批算末位不同、排序换位。

## 只标不跑

和 `guji recheck` 一样只写 manifest 的格级失效，跑还是 `guji pipeline … --from glyph_match`。
本模块不在任何 Step 的 `code_deps` 里，改它不动指纹。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

import numpy as np

CHUNK = 64          # 与 steps.glyph_match._PageBatch.CHUNK 一致


def _digest(a: np.ndarray) -> bytes:
    return hashlib.sha1(repr((a.shape, a.dtype.str)).encode() + np.ascontiguousarray(a).tobytes()).digest()


@dataclass
class LibView:
    """一版库在 5a 眼里的样子：整库匹配器、刻本子库，加点名要比的几张表。"""
    full: object
    sub: object | None
    confirmed: dict[str, int]
    borrowed: frozenset
    row_sig: dict[str, tuple] = field(default_factory=dict)   # 字 → 这个字全部刻例的 (id, 摘要, 是否人裁) 排序元组
    live: dict[str, set[str]] = field(default_factory=dict)
    _dig: dict[int, bytes] = field(default_factory=dict)

    def digest_of(self, m, j: int) -> bytes:
        key = (id(m), j)
        d = self._dig.get(key)
        if d is None:
            d = _digest(m._patches[j])
            self._dig[key] = d
        return d


def load_view(p, *, font_tier: bool) -> LibView:
    """按 5a 的参数 `p`（`GlyphMatchParams`，`db_path` 指到要看的那一版库）建库视图。"""
    from ..clustering.near_shape import NearShapeConfig
    from ..clustering.seeding import load_matcher_from_db
    from ..clustering.glyph_db import GlyphDB
    from ..steps.glyph_match import (_keben_subset, borrowed_ids, human_confirmed_counts,
                                     live_exemplars)
    full, _ = load_matcher_from_db(GlyphDB(p.db_path), edition=p.edition, knn_k=p.knn_k,
                                   norm_stroke=p.norm_stroke, local_shape_rerank=p.shape_pair_rerank,
                                   near_shape=NearShapeConfig.from_any(p.near_shape))
    sub = _keben_subset(full) if font_tier else None
    v = LibView(full=full, sub=sub,
                confirmed=human_confirmed_counts(p.db_path) if p.consensus_min_confirmed > 0 else {},
                borrowed=borrowed_ids(p.db_path) if p.borrow_fingerprint else frozenset(),
                live=live_exemplars(p.db_path, p.edition))
    trusted = getattr(full, "trusted_ids", None)
    rows: dict[str, list] = {}
    for j, (iid, ch) in enumerate(zip(full._ids, full._chars)):
        rows.setdefault(ch, []).append((iid, v.digest_of(full, j), trusted is None or iid in trusted))
    v.row_sig = {c: tuple(sorted(r)) for c, r in rows.items()}
    return v


def _topk(m, sims: np.ndarray, cell_id: str | None, view: LibView) -> tuple:
    """同 `GlyphMatcher._match` 的取邻居：摘同格、argsort 取前 k。"""
    if not m._ids:
        return ()
    if cell_id is not None:
        excl = m._same_cell_rows(cell_id)
        if excl:
            sims = sims.copy()
            sims[list(excl)] = -np.inf
    else:
        excl = set()
    top = [int(j) for j in np.argsort(-sims)[: m.k] if int(j) not in excl]
    return tuple((m._ids[j], m._chars[j], view.digest_of(m, j)) for j in top)


def page_neighbours(view: LibView, norms: list[np.ndarray], cell_ids: list[str],
                    exclude_self: bool) -> list[tuple]:
    """本页每个查询（顺序同 `_page_queries`）的邻居签名：(刻本库前 k, 整库前 k)。"""
    out: list[tuple] = []
    mats = [m for m in (view.sub, view.full) if m is not None]
    # 逐张提特征，同 `_PageBatch._feat`（不整批提：怕向量化与逐张末位不同）
    feats = [np.asarray(view.full._feature.extract(n[None, ...])[0], dtype=np.float32) for n in norms]
    S = {}
    for c0 in range(0, len(norms), CHUNK):
        Q = np.stack(feats[c0:c0 + CHUNK])
        for m in mats:
            F = m.library_matrix()
            S[id(m)] = Q @ F.T if F.ndim == 2 and F.shape[0] else None
        for i in range(c0, min(c0 + CHUNK, len(norms))):
            cid = cell_ids[i] if exclude_self else None
            sig = []
            for m in mats:
                s = S[id(m)]
                sig.append(_topk(m, s[i - c0], cid, view) if s is not None else ())
            out.append(tuple(sig))
    return out


def _rec_chars(r) -> set[str]:
    from ..steps.glyph_match import _rec_chars as rc
    return rc(r)


def cell_reasons(r, nb_old: list[tuple], nb_new: list[tuple], old: LibView, new: LibView, p) -> list[str]:
    """一格（`MatchRec`）该不该重算；`nb_*` 是这一格及其候选试切的邻居签名（顺序同 `_page_queries`）。"""
    why: list[str] = []
    if r.guard == "timeout":
        why.append("timeout")
    if nb_old != nb_new:
        why.append("knn")
    if r.matched_id and r.char not in new.live.get(r.matched_id, ()):
        why.append("dead")
    chars = _rec_chars(r)
    k = p.consensus_min_confirmed
    # 升过档的格产物里记着当时的人裁例数（`via="consensus:<n>"`），例数一变记录就不逐字节相同
    upgraded = (r.via or "").startswith("consensus:") and old.confirmed.get(r.char, 0) != new.confirmed.get(r.char, 0)
    if upgraded or (k > 0 and any((old.confirmed.get(c, 0) >= k) != (new.confirmed.get(c, 0) >= k) for c in chars)):
        why.append("consensus")
    ns = r.near_shape or {}
    if p.near_shape not in (None, False) and ns.get("pair"):
        if any(old.row_sig.get(c) != new.row_sig.get(c) for c in ns["pair"]):
            why.append("near_shape")
    if p.shape_pair_rerank:
        from ..clustering.match import _SHAPE_PAIR_OF
        if any(c in _SHAPE_PAIR_OF and old.row_sig.get(c) != new.row_sig.get(c) for c in chars):
            why.append("shape_rerank")
    if old.borrowed != new.borrowed:
        why.append("borrow")
    if os.environ.get("GUJI_GUARD_IN_DB") == "1":
        from ..clustering.match import _PARTNER
        cs_old, cs_new = set(old.row_sig), set(new.row_sig)
        if any((q in cs_old) != (q in cs_new) for c in chars for q in _PARTNER.get(c, ())):
            why.append("partner")
    return why


def page_queries(ctx, page: int, chars, normalize_patch) -> tuple[list[np.ndarray], list[str], dict[str, list[int]]]:
    """同 `steps.glyph_match._page_queries`（不排除复用格）：归一图、每张图属于哪一格、格 → 图的下标。"""
    from ..steps.glyph_match import _patch
    norms: list[np.ndarray] = []
    owner: list[str] = []
    idx: dict[str, list[int]] = {}
    for cc in chars.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            if r.cell_type != "char" or not r.patch_key:
                continue
            is_punct = (getattr(r, "step3_kind", None) == "punct")
            idx.setdefault(r.id, []).append(len(norms))
            norms.append(normalize_patch(_patch(ctx, r.patch_key, page), is_punct))
            owner.append(r.id)
            for cv in (r.cand_variants or []):
                try:
                    cimg = ctx.image("char_patch", cv.patch_key)
                except (KeyError, ValueError):
                    continue
                idx[r.id].append(len(norms))
                norms.append(normalize_patch(cimg, is_punct))
                owner.append(r.id)
    return norms, owner, idx


def page_affected(ctx, page: int, pm, p, old: LibView, new: LibView) -> dict[str, list[str]]:
    """一页里该重算的格：{格 id: 理由}。`pm` 是这页现有的 `PageMatch`（上次对旧库判的）。"""
    from ..clustering.normalize import normalize_patch as _np
    chars = ctx.product("char_index", page)

    def norm(img, punct=False):
        return _np(img, stroke_width=p.norm_stroke, isotropic=punct)

    norms, owner, idx = page_queries(ctx, page, chars, norm)
    nb_old = page_neighbours(old, norms, owner, p.exclude_self)
    nb_new = page_neighbours(new, norms, owner, p.exclude_self)
    out: dict[str, list[str]] = {}
    for col in pm.columns:
        for r in col.chars if col.ok else []:
            ii = idx.get(r.id)
            if ii is None:                  # 这格现在没有图块可查（切分变了）：交给格级复用那套，照点名
                out[r.id] = ["no_query"]
                continue
            why = cell_reasons(r, [nb_old[i] for i in ii], [nb_new[i] for i in ii], old, new, p)
            if why:
                out[r.id] = why
    return out
